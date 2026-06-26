"""
federal.py

Federal executive (President, Vice President) and judicial (Supreme Court) ingestion.

- President + VP come from the @unitedstates/congress-legislators `executive.yaml`
  (keyless, authoritative, same source family as Congress) — fully automated; the
  current holders are those whose term covers today's date.
- The 9 Supreme Court justices are a small curated seed. Live Wikidata SPARQL was
  evaluated and rejected: it returns vandalism/fictional entries (e.g. fictional
  popes, "Bart Simpson" as Chief Justice) and the endpoint times out — unacceptable
  for a public-record index in an automated job. The bench changes rarely (last
  change 2022); each justice carries a Wikidata-verified QID plus a source link.

Cabinet and lower federal courts are intentionally out of scope: there is no clean,
free, automated source that stays accurate.

Everyone here is identified by Wikidata QID in external_ids["wikidata"].
"""

import datetime
import logging
import requests
import yaml

logger = logging.getLogger(__name__)

_EXECUTIVE_YAML = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/executive.yaml"
_TIMEOUT = 30

_WHITE_HOUSE = "https://www.whitehouse.gov/"
_SCOTUS_WEBSITE = "https://www.supremecourt.gov/"

_EXEC_OFFICE_BY_TYPE = {
    "prez": "President of the United States",
    "viceprez": "Vice President of the United States",
}

_EXEC_OFFICE_TYPE_BY_TYPE = {
    "prez": "president",
    "viceprez": "vice_president",
}

# Supreme Court of the United States — current bench, with Wikidata-verified QIDs.
_SUPREME_COURT = [
    {"full_name": "John Roberts",          "wikidata": "Q11153",    "seat": "Chief Justice of the United States"},
    {"full_name": "Clarence Thomas",       "wikidata": "Q11142",    "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Samuel Alito",          "wikidata": "Q11138",    "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Sonia Sotomayor",       "wikidata": "Q11107",    "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Elena Kagan",           "wikidata": "Q11105",    "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Neil Gorsuch",          "wikidata": "Q15488345", "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Brett Kavanaugh",       "wikidata": "Q4962244",  "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Amy Coney Barrett",     "wikidata": "Q29863844", "seat": "Associate Justice of the Supreme Court of the United States"},
    {"full_name": "Ketanji Brown Jackson", "wikidata": "Q6395324",  "seat": "Associate Justice of the Supreme Court of the United States"},
]


def _current_term(person: dict) -> dict | None:
    """The term (if any) whose date range covers today."""
    today = datetime.date.today().isoformat()
    current = None
    for term in person.get("terms", []) or []:
        start = str(term.get("start") or "")
        end = str(term.get("end") or "")
        if start and start <= today and (not end or today <= end):
            current = term
    return current


def get_federal_executives() -> list:
    """Current President + Vice President from executive.yaml."""
    resp = requests.get(_EXECUTIVE_YAML, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = yaml.safe_load(resp.text) or []

    people = []
    for person in data:
        term = _current_term(person)
        if not term:
            continue
        office = _EXEC_OFFICE_BY_TYPE.get(term.get("type"))
        if not office:
            continue
        name_obj = person.get("name", {}) or {}
        full_name = name_obj.get("official_full") or \
            f"{name_obj.get('first', '')} {name_obj.get('last', '')}".strip()
        id_obj = person.get("id", {}) or {}
        # Key on wikidata, not bioguide — a President/VP who was formerly in Congress
        # must not be merged into a congressional row (different office/identity here).
        external_ids = {k: v for k, v in id_obj.items() if k != "bioguide"}
        people.append({
            "full_name": full_name,
            "current_office": office,
            "party": term.get("party") or "Unknown",
            "government_level": "federal",
            "government_branch": "executive",
            "office_type": _EXEC_OFFICE_TYPE_BY_TYPE.get(term.get("type")),
            "jurisdiction": "US",
            "bioguide_id": None,
            "external_ids": external_ids,
            "aliases": [full_name],
            "contact": {
                "office_address": None,
                "phone_number": None,
                "official_website": _WHITE_HOUSE,
            },
        })
    return people


def get_supreme_court() -> list:
    """Current Supreme Court justices (curated seed)."""
    people = []
    for j in _SUPREME_COURT:
        people.append({
            "full_name": j["full_name"],
            "current_office": j["seat"],
            "party": "Nonpartisan",
            "government_level": "federal",
            "government_branch": "judicial",
            "office_type": "chief_justice" if "Chief Justice" in j["seat"] else "associate_justice",
            "jurisdiction": "US",
            "bioguide_id": None,
            "external_ids": {"wikidata": j["wikidata"]},
            "aliases": [j["full_name"]],
            "contact": {
                "office_address": "1 First Street, NE, Washington, DC 20543",
                "phone_number": "202-479-3000",
                "official_website": _SCOTUS_WEBSITE,
            },
        })
    return people


def get_federal_exec_judicial() -> list:
    """President, Vice President, and the Supreme Court."""
    print("Fetching federal executive (President/VP) + judicial (Supreme Court)...")
    people = []
    try:
        people.extend(get_federal_executives())
    except Exception as exc:
        logger.warning("[Federal] Failed to fetch executives: %s", exc)
    people.extend(get_supreme_court())
    print(f"Successfully loaded {len(people)} federal exec/judicial officials.")
    return people
