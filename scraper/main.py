import os
import sys
import time
import logging
from dotenv import load_dotenv
from loader import SupabaseLoader
from extractors.gov_api import get_congress_members
from extractors.littlesis import get_littlesis
from extractors.news_aggregator import get_news_data
from extractors.fec import get_campaign_donors
from extractors.govtrack import get_voting_records
from extractors.openstates import get_state_politicians
from extractors.openstates_votes import get_state_voting_records
from extractors.federal import get_federal_exec_judicial

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

def main():
    load_dotenv()
    print("Starting Avanguardia-Publica Phase 1 Scraper Pipeline...")
    
    # Initialize DB connection
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    loader = SupabaseLoader(supabase_url, supabase_key)

    # FEC donor enrichment only runs with a real api.data.gov key — DEMO_KEY's tiny
    # hourly limit would 429 almost immediately across all members, so it is treated
    # the same as "not configured".
    fec_key = os.environ.get("FEC_API_KEY")
    fec_enabled = bool(fec_key) and fec_key.strip().upper() != "DEMO_KEY"
    if not fec_enabled:
        print("Note: FEC_API_KEY not set (or DEMO_KEY) — skipping campaign-donor enrichment.")
    
    # 1. Fetch active Congress members
    members = get_congress_members()
    print(f"Found {len(members)} Congress members.")
    
    # 2. Iterate through each member and scrape third-party data sequentially
    total = len(members)
    errors_caught = 0
    for index, member in enumerate(members, start=1):
        try:
            print(f"\n--- [{index}/{total}] Scraping data for {member['full_name']} ---")

            # bioguide_id + the full ID crosswalk now come straight from the free
            # congress-legislators dataset (see gov_api.py) — no fragile Wikidata
            # name lookup required.
            if member.get('bioguide_id'):
                print(f"  [+] bioguide_id: {member['bioguide_id']}")

            # Upsert Hub (politicians table)
            politician_id = loader.upsert_politician(member)

            # Only proceed with third-party data if we successfully upserted the politician
            if politician_id and politician_id != "dummy-uuid":
                # Store official contact info (verified spoke, sourced from the dataset)
                loader.upsert_contact_info(politician_id, member.get('contact', {}))

                # Verified spoke: campaign donors from OpenFEC, joined by FEC candidate
                # IDs in the crosswalk (no fuzzy name matching).
                if fec_enabled:
                    fec_ids = (member.get('external_ids') or {}).get('fec') or []
                    if fec_ids:
                        print("  [*] Fetching FEC campaign donors...")
                        donors = get_campaign_donors(fec_ids)
                        loader.upsert_campaign_donors(politician_id, donors)

                # Verified spoke: roll-call votes from GovTrack, joined by the
                # govtrack person id in the crosswalk (free, no key).
                govtrack_id = (member.get('external_ids') or {}).get('govtrack')
                if govtrack_id is not None:
                    print("  [*] Fetching GovTrack voting records...")
                    votes = get_voting_records(govtrack_id)
                    loader.upsert_voting_records(politician_id, votes)

                # Scrape LittleSis in a single pass: name-matched mentions (unverified
                # text) plus structured relationships (network ties for the Connections
                # view) share one entity search.
                print("  [*] Fetching LittleSis data...")
                ls_data, ls_rels = get_littlesis(member['full_name'])
                loader.process_mentions(politician_id, ls_data, 'LittleSis')
                loader.upsert_relationships(politician_id, ls_rels)
                
                # Fetch news via multi-tier aggregator (Currents → NewsData → TheNewsAPI → GDELT)
                print("  [*] Fetching news data (multi-tier aggregator)...")
                news_data = get_news_data(member['full_name'])
                loader.process_mentions(politician_id, news_data, 'NewsAggregator')
        except Exception as e:
            print(f"  [!] Error scraping {member['full_name']}: {e}")
            errors_caught += 1
        finally:
            # Respect API rate limits for downstream services
            time.sleep(1)

    # 3. State legislators + governors (OpenStates). Hub + official contact only —
    # the federal-only enrichment (FEC/GovTrack/news) does not apply to state races
    # and would blow free news quotas across ~8,000 additional people.
    print("\n=== State legislators + governors (OpenStates) ===")
    try:
        state_people = get_state_politicians()
    except Exception as e:
        print(f"[!] Failed to fetch state politicians: {e}")
        state_people = []

    state_total = len(state_people)
    # ocd-person id -> politician_id, built as we upsert so state roll-call votes
    # (joined on the OpenStates ocd-person id) can be attached without re-querying.
    ocd_to_pid = {}
    for index, person in enumerate(state_people, start=1):
        try:
            if index % 500 == 0:
                print(f"  ... [{index}/{state_total}] state politicians processed")
            politician_id = loader.upsert_politician(person)
            if politician_id and politician_id != "dummy-uuid":
                loader.upsert_contact_info(politician_id, person.get('contact', {}))
                ocd = (person.get('external_ids') or {}).get('openstates')
                if ocd:
                    ocd_to_pid[ocd] = politician_id
        except Exception as e:
            print(f"  [!] Error upserting state politician {person.get('full_name')}: {e}")
            errors_caught += 1
        finally:
            # Brief pause every 100 records so ~8,000 back-to-back upserts don't
            # saturate the Supabase connection pool / free-tier request limits.
            if index % 100 == 0:
                time.sleep(0.1)

    # Verified spoke: state-legislature roll-call votes from the OpenStates API,
    # joined on the ocd-person id (no fuzzy names). Gated on OPENSTATES_API_KEY — with
    # no key the call is a no-op. Roll-call-centric, so one bounded crawl fans out to
    # many legislators at once (see extractors/openstates_votes.py).
    if not os.environ.get("OPENSTATES_API_KEY"):
        print("Note: OPENSTATES_API_KEY not set — skipping state voting records.")
    elif ocd_to_pid:
        print("\n=== State voting records (OpenStates API) ===")
        try:
            votes_by_ocd = get_state_voting_records(known_ocd_ids=set(ocd_to_pid))
            for ocd, records in votes_by_ocd.items():
                loader.upsert_voting_records(ocd_to_pid[ocd], records)
        except Exception as e:
            print(f"[!] Failed to fetch/store state voting records: {e}")
            errors_caught += 1

    # 4. Federal executive (President, VP) + judicial (Supreme Court). Hub + official
    # contact only; identified by Wikidata QID.
    print("\n=== Federal executive + judicial ===")
    try:
        fed_people = get_federal_exec_judicial()
    except Exception as e:
        print(f"[!] Failed to fetch federal exec/judicial: {e}")
        fed_people = []

    for person in fed_people:
        try:
            politician_id = loader.upsert_politician(person)
            if politician_id and politician_id != "dummy-uuid":
                loader.upsert_contact_info(politician_id, person.get('contact', {}))
        except Exception as e:
            print(f"  [!] Error upserting federal official {person.get('full_name')}: {e}")
            errors_caught += 1

    if errors_caught == 0:
        print("\nPipeline finished successfully.")
    else:
        print(f"\nPipeline finished with {errors_caught} errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()
