import time

import requests
import yaml

from source_health import SourceHealthTracker

_MIN_EXPECTED_CONGRESS_MEMBERS = 400


def _build_aliases(name_obj: dict) -> list:
    """Distinct name forms used to widen news/GDELT matching recall."""
    first = name_obj.get("first", "") or ""
    last = name_obj.get("last", "") or ""
    nickname = name_obj.get("nickname", "") or ""
    official_full = name_obj.get("official_full", "") or ""

    candidates = [
        official_full,
        f"{first} {last}".strip(),
    ]
    if nickname:
        candidates.append(f"{nickname} {last}".strip())

    # De-duplicate while preserving order, dropping blanks.
    seen = set()
    aliases = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            aliases.append(c)
    return aliases


def _extract_contact(term_obj: dict) -> dict:
    """Listed official contact details from the member's most recent source term."""
    return {
        "office_address": term_obj.get("address") or term_obj.get("office"),
        "phone_number": term_obj.get("phone"),
        # Prefer the official website; fall back to the contact form if no site is listed.
        "official_website": term_obj.get("url") or term_obj.get("contact_form"),
    }


def get_congress_members(health: SourceHealthTracker | None = None):
    """
    Fetches the active members of the US Congress (Senators and Representatives).
    Uses the community-maintained open dataset from the @unitedstates project.

    Each returned member carries the full free ID crosswalk (`external_ids`) and
    official contact info, so downstream spokes can be joined by stable ID rather
    than by fuzzy name matching.
    """
    url = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
    print("Fetching active members of US Congress from @unitedstates repository...")

    # Removed try-except block based on Greptile review to prevent silent failures.
    # If the network request fails, the script will crash loudly and alert the scheduler.
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = yaml.safe_load(response.text)
        if not data or not isinstance(data, list):
            raise ValueError("Failed to parse YAML: the returned data is not a list as expected.")
    except Exception as exc:
        if health:
            reason = "timeout" if isinstance(exc, requests.Timeout) else "fetch_or_parse_error"
            health.record_failure(reason, time.monotonic() - started_at)
        raise

    politicians = []
    for legislator in data:
        name_obj = legislator.get("name", {})
        id_obj = legislator.get("id", {}) or {}
        terms = legislator.get("terms", []) or []
        term_obj = terms[-1] if terms else {}

        # Format Name
        official_full = name_obj.get("official_full")
        first = name_obj.get("first", "")
        last = name_obj.get("last", "")
        full_name = official_full if official_full else f"{first} {last}".strip()

        # Format Office
        office_type = term_obj.get("type", "")
        state = term_obj.get("state", "")
        district_label = None
        if office_type == "sen":
            office = f"US Senator from {state}"
            normalized_office_type = "senator"
        elif office_type == "rep":
            district = term_obj.get("district", "")
            district_label = "At-Large" if str(district) == "0" else str(district)
            office = f"US Representative from {state}-{district_label}"
            normalized_office_type = "representative"
        else:
            office = "Unknown Office"
            normalized_office_type = None

        # Format Party
        party = term_obj.get("party", "Independent")

        # bioguide_id is the stable canonical key (its own indexed column); the rest
        # of the id block becomes the cross-reference crosswalk used to join
        # FEC / GovTrack / Wikidata data. Exclude bioguide here to avoid duplicating it.
        bioguide_id = id_obj.get("bioguide")
        external_ids = {k: v for k, v in id_obj.items() if k != "bioguide"}
        source_record_key = bioguide_id or (
            f"govtrack:{id_obj['govtrack']}" if id_obj.get("govtrack") is not None else None
        )
        if not source_record_key:
            if health:
                health.record_skip("missing_stable_source_record_key")
            continue

        politicians.append({
            "full_name": full_name,
            "current_office": office,
            "party": party,
            # 2-letter USPS state code + district for the directory location filter.
            "state": (state or "").upper() or None,
            "district": district_label,
            "government_level": "federal",
            "government_branch": "legislative" if normalized_office_type else None,
            "office_type": normalized_office_type,
            "jurisdiction": "US",
            "bioguide_id": bioguide_id,
            "external_ids": external_ids,
            "aliases": _build_aliases(name_obj),
            "contact": _extract_contact(term_obj),
            "source_system_key": "congress-legislators",
            "source_record_key": source_record_key,
            "source_catalog_slug": "congress-legislators",
            "source_endpoint_slug": "repository",
            "source_url": url,
            "raw_payload_ref": url,
            "verified_lane": "mixed",
            "source_term_key": (
                f"{term_obj.get('type') or 'office'}:"
                f"{term_obj.get('start') or 'unknown'}"
            ),
            "term_start": term_obj.get("start"),
            "term_end": term_obj.get("end"),
            "term_status": "current",
        })

    if len(politicians) < _MIN_EXPECTED_CONGRESS_MEMBERS:
        if health:
            health.record_failure(
                "snapshot_below_safety_floor", time.monotonic() - started_at
            )
            health.trip_breaker("snapshot_below_safety_floor")
        raise ValueError(
            f"Congress roster snapshot has {len(politicians)} records; "
            f"expected at least {_MIN_EXPECTED_CONGRESS_MEMBERS}"
        )
    if health:
        health.record_success(time.monotonic() - started_at)
    print(f"Successfully loaded {len(politicians)} active members of Congress.")
    return politicians
