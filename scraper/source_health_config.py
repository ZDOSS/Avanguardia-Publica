"""ETL source criticality policy.

Core roster sources must fail the run.  Independently refreshable profile spokes
remain observable in the ETL summary but do not invalidate a healthy canonical
roster, identity, and database-write run.
"""

from etl_summary import ETLRunSummary


# OpenFEC's crawl has a 900 physical-request cap, a five-consecutive-failure
# breaker, and a 25% logical-failure-rate breaker. Accumulating elapsed timeout
# seconds across a long partial-success crawl tracked crawl length rather than an
# outage, so this redundant blocking threshold is disabled. The timeout total
# remains visible in ETL_SUMMARY_JSON as a degraded source.
OPENFEC_MAX_FAILURE_SECONDS = 0.0

# An OpenStates vote request can use two 30-second transport attempts. Wait for
# ten logical requests before applying the 25% rate threshold; the larger time
# budget still bounds prolonged scattered timeouts.
OPENSTATES_VOTES_MIN_ATTEMPTS_FOR_RATE = 10
OPENSTATES_VOTES_MAX_FAILURE_SECONDS = 300.0


def build_source_health_trackers(summary: ETLRunSummary) -> dict:
    """Configure core sources to block and independently refreshable spokes to degrade."""
    return {
        # These sources create or reconcile canonical profiles, so an outage must
        # keep the ETL failed and prevent a downstream deploy from masking it.
        "congress_roster": summary.source_tracker(
            "congress_roster", min_attempts_for_rate=1, max_failure_rate=0.5
        ),
        "openstates_people": summary.source_tracker(
            "openstates_people", min_attempts_for_rate=1, max_failure_rate=0.5
        ),
        "federal_executives": summary.source_tracker(
            "federal_executives", min_attempts_for_rate=1, max_failure_rate=0.5
        ),
        "scotus_seed": summary.source_tracker(
            "scotus_seed", min_attempts_for_rate=1, max_failure_rate=0.5
        ),
        # These are independently refreshable profile spokes. Their failed status
        # stays in ETL_SUMMARY_JSON, but a provider quota/outage must not fail a
        # healthy canonical roster, identity, and database write run.
        "openfec": summary.source_tracker(
            "openfec",
            min_attempts_for_rate=10,
            max_failure_seconds=OPENFEC_MAX_FAILURE_SECONDS,
            affects_run=False,
        ),
        "govtrack": summary.source_tracker(
            "govtrack", min_attempts_for_rate=10, affects_run=False
        ),
        # Read-only reconciliation against an official Senate source. It cannot
        # mutate canonical data or voting_records, so a temporary source outage
        # remains observable without invalidating the ETL run.
        "senate_roll_call_shadow": summary.source_tracker(
            "senate_roll_call_shadow", min_attempts_for_rate=3, affects_run=False
        ),
        # Health for the bounded Clerk fetch plus vote-centric GovTrack comparison
        # remains nonblocking in shadow-only mode. The separate write tracker below
        # becomes blocking only when the dormant authoritative path is attempted.
        "house_roll_call_shadow": summary.source_tracker(
            "house_roll_call_shadow", min_attempts_for_rate=3, affects_run=False
        ),
        # Authoritative House writes are opt-in, but any attempted write failure
        # invalidates the run rather than allowing a partial batch to look healthy.
        "house_roll_call_write": summary.source_tracker(
            "house_roll_call_write",
            min_attempts_for_rate=1,
            max_failure_rate=0.0,
            affects_run=True,
        ),
        # The private worklist is operational observability, not a roster or
        # profile write path. Its unavailability must remain visible but cannot
        # invalidate a healthy canonical-data run.
        "source_catalog_review": summary.source_tracker(
            "source_catalog_review", min_attempts_for_rate=1, affects_run=False
        ),
        # Freshness is derived from private provenance records. It informs review
        # and source reliability work but must not fail a healthy canonical write.
        "source_record_freshness": summary.source_tracker(
            "source_record_freshness", min_attempts_for_rate=1, affects_run=False
        ),
        "openstates_votes": summary.source_tracker(
            "openstates_votes",
            min_attempts_for_rate=OPENSTATES_VOTES_MIN_ATTEMPTS_FOR_RATE,
            max_failure_seconds=OPENSTATES_VOTES_MAX_FAILURE_SECONDS,
            affects_run=False,
        ),
        "house_disclosures": summary.source_tracker(
            "house_disclosures",
            min_attempts_for_rate=2,
            max_failure_rate=0.75,
            affects_run=False,
        ),
        "littlesis": summary.source_tracker(
            "littlesis",
            min_attempts_for_rate=10,
            max_failure_rate=0.5,
            affects_run=False,
        ),
        "news": summary.source_tracker(
            "news", min_attempts_for_rate=10, affects_run=False
        ),
    }
