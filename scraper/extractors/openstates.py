"""
openstates.py

State legislator + governor ingestion from the open-source openstates/people
dataset (keyless YAML, same approach as gov_api.py uses for Congress). Each person
carries a stable `ocd-person` id in external_ids["openstates"], which is the identity
key the loader matches on — state legislators commonly share names across states and
with federal members, so name matching is unsafe here.

The whole repo is pulled once as a ~5 MB tarball and walked locally, avoiding
thousands of per-file GitHub requests (and the 60 req/hour unauthenticated limit).
"""

import io
import tarfile
import logging
import requests
import yaml

logger = logging.getLogger(__name__)

_TARBALL_URL = "https://github.com/openstates/people/archive/refs/heads/main.tar.gz"
_TIMEOUT = 120

# Role types we ingest, mapped to office strings the directory classifier recognises.
# Other state-executive roles (AG, treasurer, ...) are intentionally out of scope.
_OFFICE_ROLE_TYPES = {"upper", "lower", "governor", "lt_governor"}


def _current_role(roles: list) -> dict | None:
    """Active role: one without an end_date, else the latest by start_date."""
    if not roles:
        return None
    open_roles = [r for r in roles if not r.get("end_date")]
    pool = open_roles or roles
    return max(pool, key=lambda r: str(r.get("start_date") or ""))


def _office_string(role: dict, state: str) -> str | None:
    state = state.upper()
    rtype = role.get("type")
    district = role.get("district")
    dsuffix = f" District {district}" if district else ""
    if rtype == "governor":
        return f"Governor of {state}"
    if rtype == "lt_governor":
        return f"Lieutenant Governor of {state}"
    if rtype == "upper":
        return f"State Senator from {state}{dsuffix}"
    if rtype == "lower":
        return f"State Representative from {state}{dsuffix}"
    return None


def _classification(role: dict, state: str) -> dict:
    rtype = role.get("type")
    office_type = {
        "governor": "governor",
        "lt_governor": "lieutenant_governor",
        "upper": "senator",
        "lower": "representative",
    }.get(rtype)
    branch = {
        "governor": "executive",
        "lt_governor": "executive",
        "upper": "legislative",
        "lower": "legislative",
    }.get(rtype)
    return {
        "government_level": "state",
        "government_branch": branch,
        "office_type": office_type,
        "jurisdiction": (state or "").upper() or None,
    }


def _party(person: dict) -> str:
    parties = person.get("party") or []
    if not parties or not isinstance(parties, list):
        return "Unknown"
    # Prefer an entry with no end_date (current affiliation); fall back to the last
    # entry, which OpenStates records as the most recent in history ordering.
    current = next((p for p in parties if not p.get("end_date")), parties[-1])
    return current.get("name") or "Unknown"


def _aliases(person: dict) -> list:
    out = []
    primary = person.get("name")
    given_family = f"{person.get('given_name', '')} {person.get('family_name', '')}".strip()
    for v in (primary, given_family):
        if v and v not in out:
            out.append(v)
    for on in person.get("other_names") or []:
        n = on.get("name")
        if n and n not in out:
            out.append(n)
    return out


def _external_ids(person: dict) -> dict:
    ids = {"openstates": person.get("id")}
    for oi in person.get("other_identifiers") or []:
        scheme = oi.get("scheme")
        ident = oi.get("identifier")
        if scheme and ident:
            ids[scheme] = ident
    return ids


def _contact(person: dict) -> dict:
    offices = person.get("offices") or []
    office = next((o for o in offices if o.get("classification") == "capitol"), None)
    office = office or (offices[0] if offices else {})
    links = person.get("links") or []
    website = links[0].get("url") if links else None
    return {
        "office_address": office.get("address"),
        "phone_number": office.get("voice"),
        "official_website": website,
    }


def _state_from_path(path: str) -> str:
    # people-main/data/{state}/legislature/Name-uuid.yml
    parts = path.split("/")
    try:
        return parts[parts.index("data") + 1]
    except (ValueError, IndexError):
        return ""


def _is_state_dataset_code(state: str) -> bool:
    return bool(state) and state.lower() != "us"


def _map_person(person: dict, state: str) -> dict | None:
    if not _is_state_dataset_code(state):
        return None

    # The ocd-person id is the identity key the loader matches on. Without it a
    # state legislator would fall through to unsafe name matching, so skip the
    # record entirely if it is missing.
    person_id = person.get("id")
    if not person_id:
        return None
    role = _current_role(person.get("roles") or [])
    if not role or role.get("type") not in _OFFICE_ROLE_TYPES:
        return None
    office = _office_string(role, state)
    name = person.get("name")
    if not office or not name:
        return None
    district = role.get("district")
    return {
        "full_name": name,
        "current_office": office,
        "party": _party(person),
        # 2-letter USPS state code + district for the directory location filter.
        "state": (state or "").upper() or None,
        "district": str(district) if district is not None else None,
        **_classification(role, state),
        "bioguide_id": None,
        "external_ids": _external_ids(person),
        "aliases": _aliases(person),
        "contact": _contact(person),
    }


def get_state_politicians() -> list:
    """
    Returns state legislators + governors from openstates/people. Each carries a
    stable `ocd-person` id in external_ids["openstates"] for identity matching.
    """
    print("Fetching state legislators + governors from openstates/people...")
    resp = requests.get(_TARBALL_URL, timeout=_TIMEOUT)
    resp.raise_for_status()

    people = []
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tar:
        for member in tar.getmembers():
            path = member.name
            if not path.endswith(".yml") or "/data/" not in path:
                continue
            if "/legislature/" not in path and "/executive/" not in path:
                continue
            state = _state_from_path(path)
            if not _is_state_dataset_code(state):
                continue
            try:
                f = tar.extractfile(member)
                if f is None:
                    continue
                person = yaml.safe_load(f.read())
                mapped = _map_person(person, state)
                if mapped:
                    people.append(mapped)
            except Exception as exc:
                logger.warning("[OpenStates] Failed to parse %s: %s", path, exc)
                continue

    print(f"Successfully loaded {len(people)} state legislators + governors.")
    return people
