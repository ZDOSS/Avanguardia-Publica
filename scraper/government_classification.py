FEDERAL = "federal"
STATE = "state"
LOCAL = "local"

EXECUTIVE = "executive"
LEGISLATIVE = "legislative"
JUDICIAL = "judicial"


def normalize_government_classification(member_data: dict) -> dict:
    """
    Return normalized government classification fields for a politician row.

    Source-provided values win. The office-string fallback keeps old extractors and
    pre-backfill records usable while new sources migrate to structured metadata.
    """
    office = (member_data.get("current_office") or "").lower()
    state = _clean_state(member_data.get("state"))
    external_ids = member_data.get("external_ids") or {}

    inferred = _infer_from_office(
        office=office,
        state=state,
        has_bioguide=bool(member_data.get("bioguide_id")),
        has_openstates=bool(external_ids.get("openstates")),
    )

    if _looks_like_federal_house_office(office):
        level = inferred["government_level"]
        branch = inferred["government_branch"]
        office_type = inferred["office_type"]
        jurisdiction = inferred["jurisdiction"]
    else:
        level = _clean_value(member_data.get("government_level")) or inferred["government_level"]
        branch = _clean_value(member_data.get("government_branch")) or inferred["government_branch"]
        office_type = _clean_value(member_data.get("office_type")) or inferred["office_type"]
        jurisdiction = _clean_jurisdiction(member_data.get("jurisdiction")) or inferred["jurisdiction"]

    return {
        "government_level": level,
        "government_branch": branch,
        "office_type": office_type,
        "jurisdiction": jurisdiction,
    }


def normalize_location_fields(member_data: dict) -> dict:
    """
    Return normalized state/district fields for directory location filters.
    """
    office = (member_data.get("current_office") or "").lower()
    office_upper = (member_data.get("current_office") or "").upper()
    state = _clean_state(member_data.get("state"))
    district = _clean_district(member_data.get("district"))

    if _looks_like_federal_house_office(office):
        parsed = _parse_us_district(district, office_upper)
        if parsed:
            return {"state": parsed["state"], "district": parsed["district"]}

    return {"state": state, "district": district}


def _infer_from_office(office: str, state: str | None, has_bioguide: bool, has_openstates: bool) -> dict:
    level = None
    branch = None
    office_type = None
    jurisdiction = None

    # Congressional district strings like "US District FL-4" can arrive from
    # generic civic sources even when the title text says "State Representative".
    # Treat those as federal before applying state-title fallbacks.
    if _looks_like_federal_house_office(office):
        level, branch, office_type = FEDERAL, LEGISLATIVE, "representative"

    # State rules must run before broad federal/local substring rules.
    elif "lieutenant governor" in office:
        level, branch, office_type = STATE, EXECUTIVE, "lieutenant_governor"
    elif office.startswith("governor of") or "governor," in office:
        level, branch, office_type = STATE, EXECUTIVE, "governor"
    elif "state senator" in office or "state senate" in office:
        level, branch, office_type = STATE, LEGISLATIVE, "senator"
    elif (
        "state representative" in office
        or "state assembly" in office
        or "state house" in office
        or "house of delegates" in office
        or "assembly member" in office
    ):
        level, branch, office_type = STATE, LEGISLATIVE, "representative"
    elif has_openstates:
        level = STATE

    # Federal.
    elif "vice president" in office:
        level, branch, office_type = FEDERAL, EXECUTIVE, "vice_president"
    elif "president of the united states" in office:
        level, branch, office_type = FEDERAL, EXECUTIVE, "president"
    elif any(token in office for token in ("u.s. senator", "us senator", "united states senator", "senator from")):
        level, branch, office_type = FEDERAL, LEGISLATIVE, "senator"
    elif any(
        token in office
        for token in (
            "u.s. representative",
            "us representative",
            "representative from",
            "member of the u.s. house",
            "member of congress",
            "house of representatives",
        )
    ):
        level, branch, office_type = FEDERAL, LEGISLATIVE, "representative"
    elif "chief justice" in office:
        level, branch, office_type = FEDERAL, JUDICIAL, "chief_justice"
    elif "associate justice" in office or "supreme court" in office:
        level, branch, office_type = FEDERAL, JUDICIAL, "associate_justice"
    elif has_bioguide:
        level = FEDERAL

    # Local.
    elif "mayor of" in office or "mayor," in office or office == "mayor" or office.startswith("mayor "):
        level, branch, office_type = LOCAL, EXECUTIVE, "mayor"
    elif "city manager" in office:
        level, branch, office_type = LOCAL, EXECUTIVE, "city_manager"
    elif "town administrator" in office:
        level, branch, office_type = LOCAL, EXECUTIVE, "town_administrator"
    elif any(token in office for token in ("city council", "alderman", "alderperson", "town board")):
        level, branch, office_type = LOCAL, LEGISLATIVE, "council_member"
    elif "sheriff" in office:
        level, branch, office_type = LOCAL, EXECUTIVE, "sheriff"
    elif "district attorney" in office or "county prosecutor" in office:
        level, branch, office_type = LOCAL, EXECUTIVE, "district_attorney"
    elif any(
        token in office
        for token in ("county commissioner", "county executive", "county supervisor", "board of supervisors")
    ):
        level, branch, office_type = LOCAL, EXECUTIVE, "county_commissioner"
    elif "school board" in office or "board of education" in office or "school district" in office:
        level, branch, office_type = LOCAL, LEGISLATIVE, "school_board_member"
    elif "county" in office:
        level = LOCAL

    if level == FEDERAL:
        jurisdiction = "US"
    elif level == STATE:
        jurisdiction = state

    return {
        "government_level": level,
        "government_branch": branch,
        "office_type": office_type,
        "jurisdiction": jurisdiction,
    }


def _looks_like_federal_house_office(office: str) -> bool:
    return (
        "representative" in office
        and ("us district" in office or "u.s. district" in office)
    )


def _parse_us_district(district: str | None, office_upper: str) -> dict | None:
    import re

    for value, pattern in (
        (district or "", r"^([A-Z]{2})-([0-9A-Z-]+)$"),
        (office_upper, r"U\.?S\.? DISTRICT ([A-Z]{2})-([0-9A-Z-]+)"),
    ):
        match = re.search(pattern, value)
        if match:
            return {"state": match.group(1), "district": match.group(2)}

    return None


def _clean_value(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned or None


def _clean_state(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().upper()
    return cleaned or None


def _clean_district(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _clean_jurisdiction(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().upper()
    return cleaned or None
