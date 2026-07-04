MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT = 500


def parse_non_negative_int(value, *, name: str, default: int = 0) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        parsed = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


def state_unverified_enrichment_config(env: dict) -> dict:
    requested_limit = parse_non_negative_int(
        env.get("STATE_UNVERIFIED_ENRICHMENT_LIMIT"),
        name="STATE_UNVERIFIED_ENRICHMENT_LIMIT",
    )
    offset = parse_non_negative_int(
        env.get("STATE_UNVERIFIED_ENRICHMENT_OFFSET"),
        name="STATE_UNVERIFIED_ENRICHMENT_OFFSET",
    )
    return {
        "requested_limit": requested_limit,
        "limit": min(requested_limit, MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT),
        "offset": offset,
        "capped": requested_limit > MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT,
    }


def should_enrich_state_profile(position: int, *, limit: int, offset: int) -> bool:
    if limit <= 0:
        return False
    return offset <= position < offset + limit
