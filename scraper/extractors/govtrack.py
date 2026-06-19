"""
govtrack.py

Voting-record ingestion from the free GovTrack API (no key required), joined by the
GovTrack person ID carried in politicians.external_ids["govtrack"] (from the
congress-legislators crosswalk) — no fuzzy name matching.

This is a VERIFIED spoke (official roll-call votes), so it lands in voting_records.

Mirrors fec.py's bounded design: a per-run request budget plus a consecutive-failure
circuit breaker, so a sustained GovTrack outage can't hang the pipeline.
"""

import logging
import requests

logger = logging.getLogger(__name__)

_BASE = "https://www.govtrack.us/api/v2"
_TIMEOUT = 15

_MAX_REQUESTS = 700
_MAX_CONSECUTIVE_FAILURES = 5
_request_count = 0
_consecutive_failures = 0
_breaker_tripped = False

# Default number of most-recent votes to pull per politician.
_VOTES_PER_POLITICIAN = 25


def reset_budget() -> None:
    """
    Reset the per-run request budget and circuit breaker. GitHub Actions uses one
    process per run so this is implicit there; tests or long-lived reuse should call
    this between runs to avoid the budget accumulating or the breaker staying tripped.
    """
    global _request_count, _consecutive_failures, _breaker_tripped
    _request_count = 0
    _consecutive_failures = 0
    _breaker_tripped = False


def _get(path: str, params: dict):
    """Single budgeted GET against GovTrack. Returns parsed JSON or None on failure."""
    global _request_count, _breaker_tripped, _consecutive_failures

    if _breaker_tripped or _request_count >= _MAX_REQUESTS:
        _breaker_tripped = True
        return None

    # Count the attempt before issuing it, so timeouts/connection errors also draw
    # down the budget (otherwise a sustained outage never trips the count breaker).
    _request_count += 1
    try:
        resp = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("[GovTrack] Rate limit (429) hit — tripping breaker for this run.")
            _breaker_tripped = True
            return None
        resp.raise_for_status()
        _consecutive_failures = 0
        return resp.json()
    except Exception as exc:
        logger.warning("[GovTrack] Request failed for %s: %s", path, exc)
        _consecutive_failures += 1
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[GovTrack] %d consecutive failures — tripping breaker for this run.",
                _consecutive_failures,
            )
            _breaker_tripped = True
        return None


def _map_vote(obj: dict) -> dict | None:
    vote = obj.get("vote") or {}
    option = obj.get("option") or {}

    bill_name = vote.get("question")
    created = vote.get("created")
    # bill_name and vote_date are NOT NULL in the schema — skip incomplete rows.
    if not bill_name or not created:
        return None
    vote_date = created.split("T")[0]

    # Compose a readable summary from the result, chamber, and a source link.
    parts = []
    if vote.get("result"):
        parts.append(vote["result"])
    if vote.get("chamber_label"):
        parts.append(vote["chamber_label"])
    summary = " · ".join(parts)
    if vote.get("link"):
        summary = f"{summary} — {vote['link']}" if summary else vote["link"]

    # Stable id for this roll call, shared by everyone who voted on it — powers the exact
    # co-voting self-join (get_covoting). Namespaced 'govtrack:' so it can never collide
    # with an OpenStates ocd-vote id. jurisdiction is NULL: these are federal votes.
    vote_id = vote.get("id")
    roll_call_id = f"govtrack:{vote_id}" if vote_id is not None else None

    return {
        "bill_name": bill_name,
        "bill_summary": summary or None,
        "vote_cast": option.get("value"),
        "vote_date": vote_date,
        "roll_call_id": roll_call_id,
        "jurisdiction": None,
    }


def get_voting_records(govtrack_id, limit: int = _VOTES_PER_POLITICIAN) -> list:
    """
    Returns the most recent roll-call votes cast by a politician, keyed by their
    GovTrack person ID (politicians.external_ids["govtrack"]). Bounded and rate-limit
    aware. Output dicts match the voting_records columns; deduped on
    (bill_name, vote_date) so a single upsert batch never contains duplicate
    conflict keys.
    """
    if not govtrack_id:
        return []

    data = _get(
        "/vote_voter/",
        {"person": govtrack_id, "sort": "-created", "limit": limit},
    )
    if not data:
        return []

    records: dict[tuple, dict] = {}
    # `or []` (not a .get default) guards against {"objects": null} from the API.
    for obj in data.get("objects") or []:
        mapped = _map_vote(obj)
        if mapped:
            records[(mapped["bill_name"], mapped["vote_date"])] = mapped

    return list(records.values())
