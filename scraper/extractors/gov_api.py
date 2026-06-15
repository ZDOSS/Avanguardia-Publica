import requests
import yaml


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
    """Official contact info from the member's most recent term (free, authoritative)."""
    return {
        "office_address": term_obj.get("address") or term_obj.get("office"),
        "phone_number": term_obj.get("phone"),
        # Prefer the official website; fall back to the contact form if no site is listed.
        "official_website": term_obj.get("url") or term_obj.get("contact_form"),
    }


def get_congress_members():
    """
    Fetches the active members of the US Congress (Senators and Representatives).
    Uses the official open-source repository maintained by the @unitedstates project.

    Each returned member carries the full free ID crosswalk (`external_ids`) and
    official contact info, so downstream spokes can be joined by stable ID rather
    than by fuzzy name matching.
    """
    url = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
    print("Fetching active members of US Congress from @unitedstates repository...")

    # Removed try-except block based on Greptile review to prevent silent failures.
    # If the network request fails, the script will crash loudly and alert the scheduler.
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = yaml.safe_load(response.text)

    if not data or not isinstance(data, list):
        raise ValueError("Failed to parse YAML: the returned data is not a list as expected.")

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
        if office_type == "sen":
            office = f"US Senator from {state}"
        elif office_type == "rep":
            district = term_obj.get("district", "")
            district_str = "At-Large" if str(district) == "0" else str(district)
            office = f"US Representative from {state}-{district_str}"
        else:
            office = "Unknown Office"

        # Format Party
        party = term_obj.get("party", "Independent")

        # bioguide_id is the stable canonical key; the rest of the id block becomes
        # the cross-reference crosswalk used to join FEC / GovTrack / Wikidata data.
        bioguide_id = id_obj.get("bioguide")

        politicians.append({
            "full_name": full_name,
            "current_office": office,
            "party": party,
            "bioguide_id": bioguide_id,
            "external_ids": id_obj,
            "aliases": _build_aliases(name_obj),
            "contact": _extract_contact(term_obj),
        })

    print(f"Successfully loaded {len(politicians)} active members of Congress.")
    return politicians
