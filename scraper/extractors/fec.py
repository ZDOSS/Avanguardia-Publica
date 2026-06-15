"""
fec.py

Campaign-donor ingestion from the OpenFEC API (free; key from https://api.data.gov).
Joined by the FEC candidate IDs carried in politicians.external_ids["fec"], which come
from the @unitedstates/congress-legislators crosswalk — no fuzzy name matching.

This is a VERIFIED spoke (official FEC filings), so it lands in campaign_donors, not
unconfirmed_mentions.

Volume control: a single committee can have >100k itemized receipts and a free
api.data.gov key allows ~1,000 requests/hour, so we deliberately bound the work:
  * at most one (most-recently-active) principal committee per candidate,
  * one page of the most recent receipts,
  * a module-level per-run request budget that trips a circuit breaker.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.open.fec.gov/v1"
_TIMEOUT = 15

# Per-run request budget to stay under the free hourly rate limit. Reset per process.
_MAX_REQUESTS = 900
# Trip the breaker after this many consecutive failures so a sustained outage bounds
# wall-clock time (without this, the budget alone allows _MAX_REQUESTS * _TIMEOUT of
# hanging on timeouts).
_MAX_CONSECUTIVE_FAILURES = 5
_request_count = 0
_consecutive_failures = 0
_breaker_tripped = False

# Default number of recent donors to pull per politician.
_DONORS_PER_POLITICIAN = 25


def reset_budget() -> None:
    """
    Reset the per-run request budget and circuit breaker. GitHub Actions uses one
    process per run so this is implicit there, but tests (or any code that reuses the
    module in a long-lived process) should call this between runs to avoid the budget
    accumulating or the breaker staying tripped across calls.
    """
    global _request_count, _breaker_tripped, _consecutive_failures
    _request_count = 0
    _consecutive_failures = 0
    _breaker_tripped = False


def _api_key() -> str:
    return os.environ.get("FEC_API_KEY") or "DEMO_KEY"


def _get(path: str, params: dict):
    """Single budgeted GET against OpenFEC. Returns parsed JSON or None on failure."""
    global _request_count, _breaker_tripped, _consecutive_failures

    if _breaker_tripped or _request_count >= _MAX_REQUESTS:
        _breaker_tripped = True
        return None

    params = dict(params)
    params["api_key"] = _api_key()
    # Count the attempt before issuing it, so timeouts/connection errors also draw
    # down the budget (otherwise a sustained outage never trips the count breaker).
    _request_count += 1
    try:
        resp = requests.get(f"{_BASE}{path}", params=params, timeout=_TIMEOUT)
        if resp.status_code == 429:
            logger.warning("[FEC] Rate limit (429) hit — tripping breaker for this run.")
            _breaker_tripped = True
            return None
        resp.raise_for_status()
        _consecutive_failures = 0
        return resp.json()
    except Exception as exc:
        logger.warning("[FEC] Request failed for %s: %s", path, exc)
        _consecutive_failures += 1
        if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            logger.warning(
                "[FEC] %d consecutive failures — tripping breaker for this run.",
                _consecutive_failures,
            )
            _breaker_tripped = True
        return None


def _most_active_principal_committee(candidate_id: str):
    """Return the principal campaign committee id with the most recent filing activity."""
    data = _get(f"/candidate/{candidate_id}/committees/", {"designation": "P"})
    if not data:
        return None
    committees = data.get("results", [])
    if not committees:
        return None
    # Prefer the committee that filed most recently (handles candidates with several
    # principal committees across cycles).
    committees.sort(key=lambda c: (c.get("last_file_date") or ""), reverse=True)
    return committees[0].get("committee_id")


def _recent_receipts(committee_id: str, limit: int) -> list:
    data = _get(
        "/schedules/schedule_a/",
        {
            "committee_id": committee_id,
            "per_page": min(limit, 100),
            "sort": "-contribution_receipt_date",
        },
    )
    if not data:
        return []
    return data.get("results", [])[:limit]


def _map_receipt(receipt: dict) -> dict | None:
    name = receipt.get("contributor_name")
    sub_id = receipt.get("sub_id")
    # donor_name is NOT NULL and fec_transaction_id is the dedup key — skip if missing.
    if not name or not sub_id:
        return None

    date = receipt.get("contribution_receipt_date")
    donation_date = date.split("T")[0] if isinstance(date, str) and date else None

    entity_type = (receipt.get("entity_type") or "").upper()
    # IND = individual; unknown/empty entity_type (OpenFEC returns null for some
    # filings) is treated conservatively as non-PAC. Anything else (PAC, ORG, CCM,
    # PTY, COM) is an organisation.
    pac_status = bool(entity_type) and entity_type != "IND"

    return {
        "donor_name": name,
        "amount": receipt.get("contribution_receipt_amount"),
        "donation_date": donation_date,
        "pac_status": pac_status,
        "fec_transaction_id": str(sub_id),
    }


def get_campaign_donors(fec_ids: list, limit: int = _DONORS_PER_POLITICIAN) -> list:
    """
    Returns recent itemized campaign donors for a politician, keyed by their FEC
    candidate IDs (politicians.external_ids["fec"]). Bounded and rate-limit aware;
    returns whatever it gathered if the per-run budget trips. Output dicts match the
    campaign_donors columns.
    """
    if not fec_ids:
        return []

    donors: dict[str, dict] = {}
    for candidate_id in fec_ids:
        if _breaker_tripped:
            break
        committee_id = _most_active_principal_committee(candidate_id)
        if not committee_id:
            continue
        for receipt in _recent_receipts(committee_id, limit):
            mapped = _map_receipt(receipt)
            if mapped:
                # Dedup across a candidate's committees by the unique FEC sub_id.
                donors[mapped["fec_transaction_id"]] = mapped

    return list(donors.values())
