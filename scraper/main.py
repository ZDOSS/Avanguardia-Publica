import os
import sys
import time
import logging
from datetime import date
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
from extractors.financial_disclosures import get_house_disclosure_index, lookup_disclosures

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

    # Fail loud if running in CI without credentials. Without a key the loader drops into
    # dry-run mode, which writes nothing and would otherwise exit 0 and trigger the Pages
    # deploy over stale/empty data — the same silent zero-write "success" the fail-loud upsert
    # changes exist to prevent. Local runs without creds still use dry-run mode as before.
    if loader.supabase is None and (
        os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
    ):
        sys.exit(
            "FATAL: SUPABASE_URL/SUPABASE_KEY not set in CI — refusing to run a no-op "
            "pipeline that would deploy empty data. Configure the repository secrets."
        )

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

    # House financial-disclosure filings (verified spoke) from the official House Clerk bulk
    # feed — filing-level only (member/type/date + official PDF link), keyless. Built ONCE for
    # the current + previous year and matched per-member by name below. Never fatal: an outage
    # just yields an empty index (House members only — senators/state are not in this feed).
    fd_years = [date.today().year, date.today().year - 1]
    print(f"Building House financial-disclosure index for {fd_years}...")
    house_fd_index = get_house_disclosure_index(fd_years)
    print(f"  House FD index: {len(house_fd_index)} name keys.")
    
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

                # Verified spoke: House financial-disclosure filings, matched by name against
                # the pre-built House Clerk index. Explicit House-only guard: the feed contains
                # only Representatives, so without it a Senator who shares a normalized name
                # with a Representative could be mis-attributed that member's filings — rather
                # than relying implicitly on senators being absent from the index. Exact name
                # match only — never fuzzy. Kept LAST of the spokes: it is the only one that
                # depends on migration 0005, so if 0005 is unapplied its raise (which fails the
                # run, as intended) still lets the older spokes above write first.
                is_house_member = (member.get('current_office') or '').startswith('US Representative')
                if is_house_member:
                    fd_filings = lookup_disclosures(
                        house_fd_index, [member['full_name']] + (member.get('aliases') or [])
                    )
                    if fd_filings:
                        loader.upsert_financial_disclosures(politician_id, fd_filings)
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
        # A run where (nearly) every record errors almost always means the live database
        # schema has drifted from migrations/ — e.g. a column the loader writes doesn't
        # exist yet, so every upsert raises PGRST204 ("Could not find the 'X' column ...
        # in the schema cache"). Migrations are applied MANUALLY (there is no runner); see
        # README "Applying migrations". Exiting non-zero fails the run so the deploy gate
        # (nextjs.yml workflow_run) does not ship a stale site.
        sys.exit(1)

if __name__ == "__main__":
    main()
