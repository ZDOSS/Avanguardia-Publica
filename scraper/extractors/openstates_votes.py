"""
openstates_votes.py

State-legislature roll-call ingestion from the OpenStates API v3, landing in
voting_records (a VERIFIED spoke). This is the state-level analogue of govtrack.py.

Identity needs NO bridge: each PersonVote carries `voter.id`, an OpenStates
`ocd-person` id, which is exactly what we already store in
politicians.external_ids["openstates"]. We join on it directly — no fuzzy names.
See docs/state_votes_design.md for why this source was chosen over LegiScan.

Quota-aware by design. The free tier is ~500 requests/day and 10 requests/minute, so
unlike govtrack.py (one request per politician) this is **roll-call-centric**: one
`/bills?include=votes` page returns how *every* legislator voted on ~20 bills at once,
which we fan out to our hub. We pull a bounded, recently-updated window per state, so
nightly idempotent upserts accumulate coverage over time rather than needing a full
backfill in one run. Mirrors fec.py/govtrack.py: a per-run request budget plus a
consecutive-failure circuit breaker, plus interval pacing to honour 10 req/min.

Gated like FEC_API_KEY: with no OPENSTATES_API_KEY set, get_state_voting_records()
returns an empty mapping and the pipeline simply skips state votes.
"""

import os
import time
import logging
import requests

from source_health import SourceHealthTracker

logger = logging.getLogger(__name__)

_BASE = "https://v3.openstates.org"
_TIMEOUT = 30

# Quota controls (free tier: ~500 req/day, 10 req/min). Kept under the daily cap with
# headroom; pacing keeps us under the per-minute cap. All reset per process/run.
_MAX_REQUESTS = 450
_MAX_CONSECUTIVE_FAILURES = 5
_MIN_REQUEST_INTERVAL = 6.5  # seconds between requests → ≤ ~9.2 req/min
_request_count = 0
_consecutive_failures = 0
_breaker_tripped = False
_last_request_at = 0.0

# Per-state crawl bounds. Most-recently-updated bills first; a small page budget keeps
# a single run cheap, and the rolling window means each night refreshes recent activity.
_PER_PAGE = 20
_MAX_PAGES_PER_STATE = 2
_UPDATED_SINCE_DAYS = 30

# OpenStates jurisdictions we crawl: the 50 states + DC. (Congress is "United States"
# and is intentionally excluded — federal votes already come from GovTrack.)
_JURISDICTIONS = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois",
    "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland",
    "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri", "Montana",
    "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah",
    "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
    "District of Columbia",
]


def reset_budget() -> None:
    """
    Reset the per-run request budget, breaker, and pacing clock. GitHub Actions uses
    one process per run so this is implicit there; tests or long-lived reuse should
    call it between runs.
    """
    global _request_count, _consecutive_failures, _breaker_tripped, _last_request_at
    _request_count = 0
    _consecutive_failures = 0
    _breaker_tripped = False
    _last_request_at = 0.0


def _get(
    path: str,
    params: dict,
    api_key: str,
    health: SourceHealthTracker | None = None,
):
    """Single budgeted, paced GET against OpenStates v3. Returns JSON or None."""
    global _request_count, _breaker_tripped, _consecutive_failures, _last_request_at

    if _breaker_tripped or _request_count >= _MAX_REQUESTS:
        _breaker_tripped = True
        if health:
            health.record_skip(
                "request_budget_exhausted"
                if _request_count >= _MAX_REQUESTS
                else "breaker_open"
            )
        return None

    # Honour the 10 req/min cap: wait out the remainder of the interval since the
    # last attempt before issuing this one.
    elapsed = time.monotonic() - _last_request_at
    if _last_request_at and elapsed < _MIN_REQUEST_INTERVAL:
        time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

    # Count the attempt before issuing it so timeouts/connection errors also draw down
    # the budget (otherwise a sustained outage never trips the count breaker).
    _request_count += 1
    _last_request_at = time.monotonic()
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        resp = requests.get(
            f"{_BASE}{path}",
            params=params,
            headers={"X-API-KEY": api_key},
            timeout=_TIMEOUT,
        )
        elapsed = time.monotonic() - started_at
        if not resp.ok:
            reason = f"http_{resp.status_code}"
            if health:
                health.record_failure(reason, elapsed)
            _consecutive_failures += 1
            if resp.status_code in (401, 403, 429):
                logger.warning("[OpenStates] HTTP %s; tripping breaker for this run.", resp.status_code)
                _breaker_tripped = True
                if health:
                    health.trip_breaker(reason)
            elif _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                _breaker_tripped = True
                if health:
                    health.trip_breaker("consecutive_failures")
            elif health and health.breaker_tripped:
                _breaker_tripped = True
            return None
        payload = resp.json()
        _consecutive_failures = 0
        if health:
            health.record_success(elapsed)
        return payload
    except Exception as exc:
        logger.warning("[OpenStates] Request failed for %s: %s", path, exc)
        _consecutive_failures += 1
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            health.record_failure(reason, time.monotonic() - started_at)
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[OpenStates] %d consecutive failures — tripping breaker for this run.",
                _consecutive_failures,
            )
            _breaker_tripped = True
            if health:
                health.trip_breaker("consecutive_failures")
        elif health and health.breaker_tripped:
            logger.warning("[OpenStates] Health threshold exceeded; tripping breaker for this run.")
            _breaker_tripped = True
        return None


def _updated_since() -> str:
    secs = _UPDATED_SINCE_DAYS * 86400
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - secs))


def _vote_rows_from_bill(bill: dict, jurisdiction: str | None, known_ocd: set | None):
    """
    Yield (ocd_person, voting_records-row) for every individual legislator vote on a
    bill. Rows that lack a usable voter id, bill identifier, or date are skipped
    (bill_name and vote_date are NOT NULL in the schema).

    `jurisdiction` is the state name this crawl page came from; it is carried onto each
    row for display/filtering.
    """
    identifier = bill.get("identifier")
    title = bill.get("title")
    bill_url = bill.get("openstates_url")
    if not identifier:
        return

    for event in bill.get("votes") or []:
        motion = event.get("motion_text")
        start = event.get("start_date")
        if not start:
            continue
        vote_date = str(start)[:10]
        # bill_name mirrors govtrack.py's use of the vote question: identifier plus
        # motion both reads well and keeps the (bill_name, vote_date) key distinct
        # when a bill has several roll-calls on the same day (committee + floor).
        bill_name = f"{identifier} — {motion}" if motion else identifier

        # Stable id for THIS roll call (an ocd-vote id). Every voter below shares it, so
        # it powers the exact co-voting self-join (get_covoting). Namespaced by source so
        # it can never collide with a GovTrack vote id. May be absent on older events —
        # then the row simply won't participate in co-voting.
        event_id = event.get("id")
        roll_call_id = f"openstates:{event_id}" if event_id is not None else None

        summary_parts = [p for p in (title, event.get("result")) if p]
        summary = " · ".join(summary_parts)
        if bill_url:
            summary = f"{summary} — {bill_url}" if summary else bill_url

        for pv in event.get("votes") or []:
            voter = pv.get("voter") or {}
            ocd = voter.get("id")
            if not ocd:
                continue
            if known_ocd is not None and ocd not in known_ocd:
                continue
            yield ocd, {
                "bill_name": bill_name,
                "bill_summary": summary or None,
                "vote_cast": pv.get("option"),
                "vote_date": vote_date,
                "roll_call_id": roll_call_id,
                "jurisdiction": jurisdiction,
            }


def get_state_voting_records(
    known_ocd_ids: set | None = None,
    health: SourceHealthTracker | None = None,
) -> dict:
    """
    Crawl recent state roll-calls and return {ocd_person: [voting_records rows]},
    deduped per (bill_name, vote_date) for each person so a single upsert batch never
    contains duplicate conflict keys.

    `known_ocd_ids`: if given, only votes cast by these `ocd-person` ids are kept
    (the legislators we actually have in the hub). Strongly recommended — it bounds
    memory and skips work we couldn't attach anyway.

    Returns {} (and does nothing) when OPENSTATES_API_KEY is unset.
    """
    api_key = os.environ.get("OPENSTATES_API_KEY")
    if not api_key:
        if health:
            health.record_skip("api_key_not_configured")
        return {}

    reset_budget()
    since = _updated_since()
    # ocd → {(bill_name, vote_date): row}; the inner dict dedups conflict keys.
    by_person: dict[str, dict[tuple, dict]] = {}

    for state in _JURISDICTIONS:
        for page in range(1, _MAX_PAGES_PER_STATE + 1):
            if _breaker_tripped or _request_count >= _MAX_REQUESTS:
                break
            data = _get(
                "/bills",
                {
                    "jurisdiction": state,
                    "include": "votes",
                    "sort": "updated_desc",
                    "updated_since": since,
                    "page": page,
                    "per_page": _PER_PAGE,
                },
                api_key,
                health=health,
            )
            results = (data or {}).get("results") or []
            for bill in results:
                for ocd, row in _vote_rows_from_bill(bill, state, known_ocd_ids):
                    by_person.setdefault(ocd, {})[(row["bill_name"], row["vote_date"])] = row
            # Stop early on the last/short page rather than spending budget on empties.
            if len(results) < _PER_PAGE:
                break
        if _breaker_tripped:
            logger.warning("[OpenStates] Budget/breaker reached — stopping state crawl early.")
            break

    out = {ocd: list(rows.values()) for ocd, rows in by_person.items()}
    total = sum(len(v) for v in out.values())
    print(f"OpenStates state votes: {total} rows across {len(out)} legislators "
          f"({_request_count} requests used).")
    return out
