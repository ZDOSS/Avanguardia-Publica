import argparse
import os
import sys
import time
import logging
from datetime import date
from dotenv import load_dotenv
from loader import SupabaseLoader
from etl_summary import ETLRunSummary
from source_health_config import build_source_health_trackers
from identity_health import run_identity_health_check
from source_catalog_review import run_source_catalog_review_check
from source_record_freshness import run_source_record_freshness_check
from schema_preflight import SchemaPreflightError, run_schema_preflight
from extractors.gov_api import get_congress_members
from extractors.littlesis import get_littlesis
from extractors.news_aggregator import get_news_data, get_provider_status
from extractors.fec import get_campaign_donors
from extractors.govtrack import get_voting_records
from extractors.senate_roll_calls import (
    get_recent_senate_roll_call_shadow,
    govtrack_senate_vote_casts,
)
from extractors.house_roll_calls import (
    get_recent_house_roll_call_shadow,
    govtrack_house_vote_casts,
)
from extractors.openstates import get_state_politicians
from extractors.openstates_votes import get_state_voting_records
from extractors.federal import get_federal_exec_judicial
from extractors.financial_disclosures import get_house_disclosure_index, lookup_disclosures
from unverified_enrichment import state_unverified_enrichment_config, should_enrich_state_profile

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

_MIN_CONGRESS_RECONCILIATION_RECORDS = 500
_MIN_OPENSTATES_RECONCILIATION_RECORDS = 5000


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the Avanguardia-Publica scraper.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Validate the configured Supabase schema and latest migration marker, "
            "then exit before extractors, source quotas, or ETL writes."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    load_dotenv()
    print("Starting Avanguardia-Publica Phase 1 Scraper Pipeline...")
    summary = ETLRunSummary()
    source_health = build_source_health_trackers(summary)
    news_provider_health = {
        provider: summary.source_tracker(
            f"news_{provider}",
            min_attempts_for_rate=5,
            max_failure_rate=0.5,
            affects_run=False,
        )
        for provider in ("newsapi", "currents", "newsdata", "thenewsapi", "gdelt")
    }
    
    # Initialize DB connection
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    loader = SupabaseLoader(supabase_url, supabase_key, summary=summary)

    if args.preflight_only and loader.supabase is None:
        message = (
            "SUPABASE_URL/SUPABASE_KEY are required for --preflight-only; "
            "no live schema was validated."
        )
        summary.set_schema_preflight("failed", [message])
        summary.error("configuration", message)
        summary.print(success=False)
        sys.exit(f"FATAL: {message}")

    # Fail loud if running in CI without credentials. Without a key the loader drops into
    # dry-run mode, which writes nothing and would otherwise exit 0 and trigger the Pages
    # deploy over stale/empty data — the same silent zero-write "success" the fail-loud upsert
    # changes exist to prevent. Local runs without creds still use dry-run mode as before.
    if loader.supabase is None and (
        os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"
    ):
        summary.set_schema_preflight("skipped", ["Supabase credentials missing in CI."])
        summary.error("configuration", "SUPABASE_URL/SUPABASE_KEY not set in CI")
        summary.print(success=False)
        sys.exit(
            "FATAL: SUPABASE_URL/SUPABASE_KEY not set in CI — refusing to run a no-op "
            "pipeline that would deploy empty data. Configure the repository secrets."
        )

    # Validate the live Supabase API before spending time and source quotas.
    try:
        run_schema_preflight(loader)
        summary.set_schema_preflight("passed" if loader.supabase else "skipped")
    except SchemaPreflightError as e:
        summary.set_schema_preflight("failed", e.failures)
        summary.error("schema_preflight", e)
        summary.print(success=False)
        sys.exit(str(e))

    if args.preflight_only:
        print(
            "\nPreflight-only validation passed. No extractor, source quota, "
            "or ETL write was started."
        )
        summary.print(success=True)
        return

    # FEC donor enrichment only runs with a real api.data.gov key. DEMO_KEY's tiny
    # hourly limit would 429 almost immediately across all members, so it is treated
    # the same as "not configured".
    fec_key = os.environ.get("FEC_API_KEY")
    fec_enabled = bool(fec_key) and fec_key.strip().upper() != "DEMO_KEY"
    if not fec_enabled:
        summary.skip("FEC", "FEC_API_KEY not set or DEMO_KEY")
        source_health["openfec"].record_skip("api_key_not_configured")
        print("Note: FEC_API_KEY not set (or DEMO_KEY) — skipping campaign-donor enrichment.")
    
    try:
        state_unverified_config = state_unverified_enrichment_config(os.environ)
    except ValueError as e:
        summary.error("configuration", e)
        summary.print(success=False)
        sys.exit(str(e))

    if state_unverified_config["limit"] <= 0:
        summary.skip(
            "State unverified enrichment",
            "STATE_UNVERIFIED_ENRICHMENT_LIMIT not set",
        )
        print(
            "Note: state LittleSis enrichment disabled; set "
            "STATE_UNVERIFIED_ENRICHMENT_LIMIT to run a bounded batch."
        )
    else:
        if state_unverified_config["capped"]:
            summary.increment("state_unverified_limit_cap_applied")
            summary.increment(
                "state_unverified_requested_profiles_over_cap",
                state_unverified_config["requested_limit"] - state_unverified_config["limit"],
            )
            print(
                "Note: requested state LittleSis enrichment limit "
                f"{state_unverified_config['requested_limit']} exceeds the cap; "
                f"running {state_unverified_config['limit']} profiles."
            )
        print(
            "State LittleSis enrichment enabled for "
            f"{state_unverified_config['limit']} profiles starting at offset "
            f"{state_unverified_config['offset']}."
        )

    # 1. Fetch active Congress members
    try:
        members = get_congress_members(health=source_health["congress_roster"])
    except Exception as e:
        summary.error("congress:fetch_roster", e)
        summary.print(success=False)
        sys.exit(f"FATAL: Congress roster fetch failed: {e}")
    print(f"Found {len(members)} Congress members.")

    # House financial-disclosure filings (verified spoke) from the official House Clerk bulk
    # feed — filing-level only (member/type/date + official PDF link), keyless. Built ONCE for
    # the current + previous year and matched per-member by name below. One missing year is
    # tolerated as degraded; failure of both years remains visible in source health
    # without invalidating the canonical roster run (senators/state are not in this feed).
    fd_years = [date.today().year, date.today().year - 1]
    print(f"Building House financial-disclosure index for {fd_years}...")
    house_fd_index = get_house_disclosure_index(
        fd_years, health=source_health["house_disclosures"]
    )
    print(f"  House FD index: {len(house_fd_index)} name keys.")
    
    # 2. Iterate through each member and scrape third-party data sequentially
    total = len(members)
    errors_caught = 0
    congress_upsert_errors = 0
    senate_lis_ids: set[str] = set()
    govtrack_senate_votes_by_lis_id: dict[str, dict[str, str]] = {}
    house_bioguide_ids: set[str] = set()
    govtrack_house_votes_by_bioguide_id: dict[str, dict[str, str]] = {}
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

            # The Senate's official roll-call XML uses LIS member IDs. Preserve
            # only that deterministic crosswalk for the read-only shadow source;
            # names, state, party, and office text never participate in its join.
            is_senator = member.get("office_type") == "senator"
            lis_id = str((member.get("external_ids") or {}).get("lis") or "").strip()
            if is_senator:
                if lis_id:
                    senate_lis_ids.add(lis_id)
                else:
                    source_health["senate_roll_call_shadow"].record_skip(
                        "missing_lis_join_key"
                    )

            # The House Clerk's official XML uses Bioguide IDs in its name-id
            # field. Preserve this deterministic crosswalk for the read-only
            # shadow source; names, state, party, and office text never join it.
            is_house_representative = member.get("office_type") == "representative"
            bioguide_id = str(member.get("bioguide_id") or "").strip()
            if is_house_representative:
                if bioguide_id:
                    house_bioguide_ids.add(bioguide_id)
                else:
                    source_health["house_roll_call_shadow"].record_skip(
                        "missing_bioguide_join_key"
                    )

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
                        donors = get_campaign_donors(
                            fec_ids, health=source_health["openfec"]
                        )
                        loader.upsert_campaign_donors(politician_id, donors)
                    else:
                        source_health["openfec"].record_skip("missing_fec_join_key")

                # Verified spoke: roll-call votes from GovTrack, joined by the
                # govtrack person id in the crosswalk (free, no key).
                govtrack_id = (member.get('external_ids') or {}).get('govtrack')
                if govtrack_id is not None:
                    print("  [*] Fetching GovTrack voting records...")
                    votes = get_voting_records(
                        govtrack_id, health=source_health["govtrack"]
                    )
                    loader.upsert_voting_records(politician_id, votes)
                    if is_senator and lis_id:
                        govtrack_senate_votes_by_lis_id[lis_id] = (
                            govtrack_senate_vote_casts(votes)
                        )
                    if is_house_representative and bioguide_id:
                        govtrack_house_votes_by_bioguide_id[bioguide_id] = (
                            govtrack_house_vote_casts(votes)
                        )
                else:
                    source_health["govtrack"].record_skip("missing_govtrack_join_key")

                # Scrape LittleSis in a single pass: name-matched mentions (unverified
                # text) plus structured relationships (network ties for the Connections
                # view) share one entity search.
                print("  [*] Fetching LittleSis data...")
                ls_data, ls_rels = get_littlesis(
                    member['full_name'], health=source_health["littlesis"]
                )
                loader.process_mentions(politician_id, ls_data, 'LittleSis')
                loader.upsert_relationships(politician_id, ls_rels)
                
                # Fetch news via multi-tier aggregator (Currents → NewsData → TheNewsAPI → GDELT)
                print("  [*] Fetching news data (multi-tier aggregator)...")
                news_data = get_news_data(
                    member['full_name'],
                    health=source_health["news"],
                    provider_health=news_provider_health,
                )
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
                        house_fd_index,
                        [member['full_name']] + (member.get('aliases') or []),
                        state=member.get("state"),
                        district=member.get("district"),
                        health=source_health["house_disclosures"],
                    )
                    if fd_filings:
                        loader.upsert_financial_disclosures(politician_id, fd_filings)
        except Exception as e:
            print(f"  [!] Error scraping {member['full_name']}: {e}")
            summary.error(f"congress:{member.get('full_name')}", e)
            errors_caught += 1
            congress_upsert_errors += 1
        finally:
            # Respect API rate limits for downstream services
            time.sleep(1)

    if loader.supabase:
        join_key_sources = {
            "govtrack": "missing_govtrack_join_key",
            **({"openfec": "missing_fec_join_key"} if fec_enabled else {}),
        }
        for source_name, missing_reason in join_key_sources.items():
            tracker = source_health[source_name]
            if tracker.attempts == 0:
                tracker.record_failure("no_eligible_records_or_join_keys")
                tracker.trip_breaker("no_eligible_records_or_join_keys")
            elif total and tracker.skip_reasons[missing_reason] / total > 0.10:
                tracker.record_failure("join_key_coverage_below_90_percent")
                tracker.trip_breaker("join_key_coverage_below_90_percent")

    # Official Senate roll-call XML is a bounded, read-only shadow feed. It uses
    # the exact LIS crosswalk above to compare the most recent official vote casts
    # to the same run's GovTrack records, but intentionally does not write a second
    # vote source into voting_records before the provenance/conflict-key rollout.
    print("\n=== Senate roll-call XML shadow reconciliation ===")
    try:
        senate_shadow_report = get_recent_senate_roll_call_shadow(
            senate_lis_ids,
            govtrack_senate_votes_by_lis_id,
            health=source_health["senate_roll_call_shadow"],
        )
        for counter, amount in senate_shadow_report.counters().items():
            summary.increment(counter, amount)
        print(f"  {senate_shadow_report.description()}")
    except Exception as e:
        # This source is explicitly non-blocking: preserve the health signal but
        # never turn a healthy canonical-data run into a failure for shadow-only
        # reconciliation work.
        print(f"  [!] Senate roll-call shadow unavailable: {e}")
        shadow_health = source_health["senate_roll_call_shadow"]
        shadow_health.record_attempt()
        shadow_health.record_failure("unexpected_error")

    # Official House Clerk roll-call XML is a bounded, read-only shadow feed. It
    # uses only the exact Bioguide crosswalk above to compare recent official
    # vote casts with this run's GovTrack records, and deliberately does not
    # write a second vote source into voting_records before provenance and
    # conflict-key handling are reviewed.
    print("\n=== House roll-call XML shadow reconciliation ===")
    try:
        house_shadow_report = get_recent_house_roll_call_shadow(
            house_bioguide_ids,
            govtrack_house_votes_by_bioguide_id,
            health=source_health["house_roll_call_shadow"],
        )
        for counter, amount in house_shadow_report.counters().items():
            summary.increment(counter, amount)
        print(f"  {house_shadow_report.description()}")
    except Exception as e:
        # This source is explicitly non-blocking: preserve its health signal
        # without turning a healthy canonical-data run into a shadow-only failure.
        print(f"  [!] House roll-call shadow unavailable: {e}")
        shadow_health = source_health["house_roll_call_shadow"]
        shadow_health.record_attempt()
        shadow_health.record_failure("unexpected_error")

    # 3. State legislators + governors (OpenStates). Hub + official contact by default.
    # Optional LittleSis enrichment is bounded and writes only to unverified spokes
    # (unconfirmed_mentions / relationships). FEC/GovTrack/news stay out of this loop:
    # they either do not apply to state races or would blow free quotas across ~8,000
    # additional people.
    print("\n=== State legislators + governors (OpenStates) ===")
    try:
        state_people = get_state_politicians(health=source_health["openstates_people"])
    except Exception as e:
        print(f"[!] Failed to fetch state politicians: {e}")
        summary.error("openstates:fetch_state_politicians", e)
        state_people = []

    state_total = len(state_people)
    # ocd-person id -> politician_id, built as we upsert so state roll-call votes
    # (joined on the OpenStates ocd-person id) can be attached without re-querying.
    ocd_to_pid = {}
    state_unverified_checked = 0
    state_upsert_errors = 0
    for index, person in enumerate(state_people, start=1):
        try:
            if index % 500 == 0:
                print(f"  ... [{index}/{state_total}] state politicians processed")
            politician_id = loader.upsert_politician(person)
            if politician_id and politician_id != "dummy-uuid":
                loader.upsert_contact_info(politician_id, person.get('contact', {}))
                state_position = index - 1
                if should_enrich_state_profile(
                    state_position,
                    limit=state_unverified_config["limit"],
                    offset=state_unverified_config["offset"],
                ):
                    print("  [*] Fetching state LittleSis data (unverified)...")
                    ls_data, ls_rels = get_littlesis(
                        person['full_name'], health=source_health["littlesis"]
                    )
                    loader.process_mentions(politician_id, ls_data, 'LittleSis')
                    loader.upsert_relationships(politician_id, ls_rels)
                    state_unverified_checked += 1
                    summary.increment("state_unverified_profiles_checked")
                    time.sleep(0.5)
                ocd = (person.get('external_ids') or {}).get('openstates')
                if ocd:
                    ocd_to_pid[ocd] = politician_id
        except Exception as e:
            print(f"  [!] Error upserting state politician {person.get('full_name')}: {e}")
            summary.error(f"state_politician:{person.get('full_name')}", e)
            errors_caught += 1
            state_upsert_errors += 1
        finally:
            # Brief pause every 100 records so ~8,000 back-to-back upserts don't
            # saturate the Supabase connection pool / free-tier request limits.
            if index % 100 == 0:
                time.sleep(0.1)

    skipped_by_limit = max(0, state_total - state_unverified_checked)
    if state_unverified_config["limit"] > 0 and skipped_by_limit:
        summary.increment("state_unverified_profiles_skipped_by_limit", skipped_by_limit)

    if state_people and len(state_people) < _MIN_OPENSTATES_RECONCILIATION_RECORDS:
        source_health["openstates_people"].record_skip(
            "snapshot_below_reconciliation_floor"
        )
    if (
        source_health["openstates_people"].status == "healthy"
        and state_upsert_errors == 0
        and len(state_people) >= _MIN_OPENSTATES_RECONCILIATION_RECORDS
    ):
        try:
            loader.reconcile_source_snapshot(
                "openstates",
                {
                    person["source_record_key"]
                    for person in state_people
                    if person.get("source_record_key")
                },
            )
        except Exception as e:
            summary.error("source_reconciliation:openstates", e)
            errors_caught += 1
    else:
        summary.increment("source_reconciliation_skipped_openstates")

    # Verified spoke: state-legislature roll-call votes from the OpenStates API,
    # joined on the ocd-person id (no fuzzy names). Gated on OPENSTATES_API_KEY — with
    # no key the call is a no-op. Roll-call-centric, so one bounded crawl fans out to
    # many legislators at once (see extractors/openstates_votes.py).
    if not os.environ.get("OPENSTATES_API_KEY"):
        summary.skip("OpenStates votes", "OPENSTATES_API_KEY not set")
        source_health["openstates_votes"].record_skip("api_key_not_configured")
        print("Note: OPENSTATES_API_KEY not set — skipping state voting records.")
    elif ocd_to_pid:
        print("\n=== State voting records (OpenStates API) ===")
        try:
            votes_by_ocd = get_state_voting_records(
                known_ocd_ids=set(ocd_to_pid),
                health=source_health["openstates_votes"],
            )
            for ocd, records in votes_by_ocd.items():
                loader.upsert_voting_records(ocd_to_pid[ocd], records)
        except Exception as e:
            print(f"[!] Failed to fetch/store state voting records: {e}")
            summary.error("openstates:state_voting_records", e)
            errors_caught += 1

    # 4. Federal executive (President, VP) + judicial (Supreme Court). Hub + official
    # contact only; identified by Wikidata QID.
    print("\n=== Federal executive + judicial ===")
    fed_snapshot_complete = False
    try:
        fed_people = get_federal_exec_judicial(
            executive_health=source_health["federal_executives"],
            scotus_health=source_health["scotus_seed"],
        )
        fed_snapshot_complete = True
    except Exception as e:
        print(f"[!] Failed to fetch federal exec/judicial: {e}")
        summary.error("federal_exec_judicial:fetch", e)
        errors_caught += 1
        fed_people = []

    federal_upsert_errors = 0
    scotus_upsert_errors = 0
    for person in fed_people:
        try:
            politician_id = loader.upsert_politician(person)
            if politician_id and politician_id != "dummy-uuid":
                loader.upsert_contact_info(politician_id, person.get('contact', {}))
        except Exception as e:
            print(f"  [!] Error upserting federal official {person.get('full_name')}: {e}")
            summary.error(f"federal_exec_judicial:{person.get('full_name')}", e)
            errors_caught += 1
            federal_upsert_errors += 1
            if str(person.get("source_record_key") or "").startswith("scotus-seed:"):
                scotus_upsert_errors += 1

    congress_source_people = [
        person
        for person in [*members, *fed_people]
        if person.get("source_system_key") == "congress-legislators"
    ]
    if members and len(members) < _MIN_CONGRESS_RECONCILIATION_RECORDS:
        source_health["congress_roster"].record_skip(
            "snapshot_below_reconciliation_floor"
        )
    if (
        source_health["congress_roster"].status == "healthy"
        and source_health["federal_executives"].status == "healthy"
        and fed_snapshot_complete
        and congress_upsert_errors == 0
        and federal_upsert_errors == 0
        and len(members) >= _MIN_CONGRESS_RECONCILIATION_RECORDS
    ):
        try:
            loader.reconcile_source_snapshot(
                "congress-legislators",
                {
                    person["source_record_key"]
                    for person in congress_source_people
                    if person.get("source_record_key")
                },
            )
        except Exception as e:
            summary.error("source_reconciliation:congress-legislators", e)
            errors_caught += 1
    else:
        summary.increment("source_reconciliation_skipped_congress_legislators")

    scotus_people = [
        person
        for person in fed_people
        if str(person.get("source_record_key") or "").startswith("scotus-seed:")
    ]
    if (
        source_health["scotus_seed"].status == "healthy"
        and scotus_upsert_errors == 0
        and len(scotus_people) == 9
    ):
        try:
            loader.reconcile_source_snapshot(
                "avanguardia-legacy-profile",
                {
                    person["source_record_key"]
                    for person in scotus_people
                    if person.get("source_record_key")
                },
                record_key_prefix="scotus-seed:",
            )
        except Exception as e:
            summary.error("source_reconciliation:scotus_seed", e)
            errors_caught += 1
    else:
        summary.increment("source_reconciliation_skipped_scotus_seed")

    summary.set_news_providers(get_provider_status())
    try:
        run_identity_health_check(loader, summary)
    except Exception as e:
        print(f"[!] Identity health check failed: {e}")
        summary.set_identity_health(
            "warning",
            warnings=[f"Identity health check failed to run: {e}"],
        )

    # The source catalog remains private, but aggregate worklist health makes
    # candidate/blocked review pressure observable in the ETL summary without
    # exposing source details or adding a new data-ingestion path.
    try:
        run_source_catalog_review_check(
            loader,
            summary,
            source_health["source_catalog_review"],
        )
    except Exception:
        print("[!] Source catalog review check failed unexpectedly.")
        catalog_health = source_health["source_catalog_review"]
        if not catalog_health.failures:
            if not catalog_health.attempts:
                catalog_health.record_attempt()
            catalog_health.record_failure("unexpected_error")
        summary.set_source_catalog_review(
            "warning",
            warnings=["Source catalog review check failed unexpectedly."],
        )

    # Source-record provenance stays private, while an aggregate freshness signal
    # identifies active records that have stopped appearing in healthy source runs.
    try:
        run_source_record_freshness_check(
            loader,
            summary,
            source_health["source_record_freshness"],
        )
    except Exception:
        print("[!] Source record freshness check failed unexpectedly.")
        freshness_health = source_health["source_record_freshness"]
        if not freshness_health.failures:
            if not freshness_health.attempts:
                freshness_health.record_attempt()
            freshness_health.record_failure("unexpected_error")
        summary.set_source_record_freshness(
            "warning",
            warnings=["Source record freshness check failed unexpectedly."],
        )

    for source in summary.run_blocking_source_failures():
        summary.error(
            f"source_health:{source}",
            f"severe degradation crossed the configured threshold for {source}",
        )
        errors_caught += 1

    if errors_caught == 0:
        print("\nPipeline finished successfully.")
        summary.print(success=True)
    else:
        print(f"\nPipeline finished with {errors_caught} errors.")
        # A run where (nearly) every record errors almost always means the live database
        # schema has drifted from migrations/ — e.g. a column the loader writes doesn't
        # exist yet, so every upsert raises PGRST204 ("Could not find the 'X' column ...
        # in the schema cache"). Migrations are applied MANUALLY (there is no runner); see
        # README "Applying migrations". Exiting non-zero fails the run so the deploy gate
        # (nextjs.yml workflow_run) does not ship a stale site.
        summary.print(success=False)
        sys.exit(1)

if __name__ == "__main__":
    main()
