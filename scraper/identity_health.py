from datetime import datetime, timezone


OPENSTATES_DUPLICATE_CANDIDATE_TYPE = (
    "identity_observer_blocked_deterministic_keys_match_multiple_people"
)
IDENTITY_OBSERVER_BLOCKED_PREFIX = "identity_observer_blocked_"
IDENTITY_OBSERVER_BLOCKED_LIKE_PREFIX = f"{IDENTITY_OBSERVER_BLOCKED_PREFIX}%"
IDENTITY_OBSERVER_PENDING_PREFIX = "identity_observer_pending_%"

OPENSTATES_FEDERAL_OFFICE_PATTERNS = (
    "State Representative from US District%",
    "State Senator from US District%",
)
OPENSTATES_EVIDENCE = {
    "deterministic_keys": [{"source_system_key": "openstates"}]
}


def _response_count(resp) -> int | None:
    count = getattr(resp, "count", None)
    if count is not None:
        return int(count)
    return None


def _count_rows_by_pages(
    loader,
    table_name: str,
    description: str,
    configure_query,
    page_size: int = 1000,
) -> int:
    total = 0
    start = 0
    while True:
        end = start + page_size - 1

        def operation(start=start, end=end):
            query = loader.supabase.table(table_name).select("id")
            query = configure_query(query)
            return query.range(start, end).execute()

        resp = loader.execute_supabase(
            operation,
            f"{description} fallback rows {start}-{end}",
        )
        batch = resp.data or []
        total += len(batch)
        if len(batch) < page_size:
            return total
        start += page_size


def _count_rows(loader, table_name: str, description: str, configure_query) -> int:
    def operation():
        query = loader.supabase.table(table_name).select("id", count="exact")
        query = configure_query(query)
        return query.limit(1).execute()

    count = _response_count(loader.execute_supabase(operation, description))
    if count is not None:
        return count

    return _count_rows_by_pages(loader, table_name, description, configure_query)


def _count_identity_resolution_candidates(
    loader,
    *,
    status: str | None = None,
    candidate_type: str | None = None,
    candidate_type_like: str | None = None,
    description_suffix: str,
) -> int:
    def configure(query):
        if status is not None:
            query = query.eq("status", status)
        if candidate_type is not None:
            query = query.eq("candidate_type", candidate_type)
        if candidate_type_like is not None:
            query = query.like("candidate_type", candidate_type_like)
        return query

    return _count_rows(
        loader,
        "identity_resolution_candidates",
        f"identity health count identity resolution candidates {description_suffix}",
        configure,
    )


def _count_bad_openstates_federal_profiles(loader, *, since: datetime | None = None) -> int:
    total = 0
    for pattern in OPENSTATES_FEDERAL_OFFICE_PATTERNS:
        total += _count_rows(
            loader,
            "politicians",
            f"identity health count politicians current_office like {pattern}",
            lambda query, pattern=pattern: (
                query.like("current_office", pattern)
                if since is None
                else query.like("current_office", pattern).gte(
                    "last_updated",
                    since.astimezone(timezone.utc).isoformat(),
                )
            ),
        )
    return total


def _extract_blocked_reason(candidate_type: str | None) -> str | None:
    if not candidate_type or not candidate_type.startswith(
        IDENTITY_OBSERVER_BLOCKED_PREFIX
    ):
        return None
    reason = candidate_type[len(IDENTITY_OBSERVER_BLOCKED_PREFIX) :]
    return reason or None


def _count_identity_observer_blocked_reasons(loader, *, status: str) -> dict[str, int]:
    reason_counts: dict[str, int] = {}
    query_start = 0
    page_size = 1000
    while True:
        query_end = query_start + page_size - 1

        def operation(start=query_start, end=query_end):
            return (
                loader.supabase.table("identity_resolution_candidates")
                .select("candidate_type")
                .eq("status", status)
                .like("candidate_type", IDENTITY_OBSERVER_BLOCKED_LIKE_PREFIX)
                .range(start, end)
                .execute()
            )

        resp = loader.execute_supabase(
            operation,
            f"identity health blocked reason rows status={status} {query_start}-{query_end}",
        )
        batch = resp.data or []
        for row in batch:
            reason = _extract_blocked_reason(row.get("candidate_type"))
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if len(batch) < page_size:
            break
        query_start += page_size

    return dict(sorted(reason_counts.items()))


def run_identity_health_check(loader, summary) -> dict:
    if not loader.supabase:
        health = {
            "status": "skipped",
            "warnings": ["Supabase client is not configured."],
        }
        summary.set_identity_health(**health)
        print("\n=== Identity health ===")
        print("status: skipped")
        print("  Supabase client is not configured.")
        return health

    run_started_at = getattr(summary, "started_at", datetime.now(timezone.utc))

    checks = {
        "pending_identity_observer_candidates": _count_rows(
            loader,
            "identity_resolution_candidates",
            "identity health count pending observer candidates",
            lambda query: query.like("candidate_type", "identity_observer_%").eq(
                "status",
                "pending",
            ),
        ),
        "pending_identity_observer_blocked_candidates": _count_identity_resolution_candidates(
            loader,
            status="pending",
            candidate_type_like=IDENTITY_OBSERVER_BLOCKED_LIKE_PREFIX,
            description_suffix="pending identity observer blocked candidates",
        ),
        "pending_identity_observer_blocked_candidate_reasons": _count_identity_observer_blocked_reasons(
            loader, status="pending"
        ),
        "blocked_identity_observer_candidates": _count_identity_resolution_candidates(
            loader,
            status="blocked",
            candidate_type_like=IDENTITY_OBSERVER_BLOCKED_LIKE_PREFIX,
            description_suffix="blocked identity observer candidates",
        ),
        "blocked_identity_observer_candidate_reasons": _count_identity_observer_blocked_reasons(
            loader, status="blocked"
        ),
        "pending_identity_observer_review_candidates": _count_identity_resolution_candidates(
            loader,
            status="pending",
            candidate_type_like=IDENTITY_OBSERVER_PENDING_PREFIX,
            description_suffix="pending identity observer review candidates",
        ),
        "pending_openstates_federal_duplicate_candidates": _count_rows(
            loader,
            "identity_resolution_candidates",
            "identity health count pending OpenStates federal duplicate candidates",
            lambda query: query.eq(
                "candidate_type",
                OPENSTATES_DUPLICATE_CANDIDATE_TYPE,
            ).eq("status", "pending").contains("evidence", OPENSTATES_EVIDENCE),
        ),
        "approved_openstates_federal_duplicate_candidates": _count_rows(
            loader,
            "identity_resolution_candidates",
            "identity health count approved OpenStates federal duplicate candidates",
            lambda query: query.eq(
                "candidate_type",
                OPENSTATES_DUPLICATE_CANDIDATE_TYPE,
            ).eq("status", "approved").contains("evidence", OPENSTATES_EVIDENCE),
        ),
        "openstates_federal_legacy_profiles_total": _count_bad_openstates_federal_profiles(
            loader
        ),
        "openstates_federal_legacy_profiles_refreshed_this_run": (
            _count_bad_openstates_federal_profiles(loader, since=run_started_at)
        ),
    }

    warnings = []
    if checks["pending_identity_observer_candidates"]:
        warnings.append(
            "Identity observer still has pending review candidates after this run."
        )
    if checks["pending_identity_observer_blocked_candidates"]:
        blocked_pending_breakdown = ", ".join(
            f"{reason}={count}" for reason, count in checks["pending_identity_observer_blocked_candidate_reasons"].items()
        )
        warning = "There are identity candidates blocked by conflicting deterministic identities."
        if blocked_pending_breakdown:
            warning += f" Breakdown: {blocked_pending_breakdown}."
        warnings.append(warning)
    if checks["blocked_identity_observer_candidates"]:
        blocked_reason_breakdown = ", ".join(
            f"{reason}={count}" for reason, count in checks["blocked_identity_observer_candidate_reasons"].items()
        )
        warning = "There are previously blocked identity candidates waiting for maintainer review."
        if blocked_reason_breakdown:
            warning += f" Breakdown: {blocked_reason_breakdown}."
        warnings.append(warning)
    if checks["pending_openstates_federal_duplicate_candidates"]:
        warnings.append(
            "OpenStates data/us duplicate candidates came back after cleanup."
        )
    if checks["openstates_federal_legacy_profiles_refreshed_this_run"]:
        warnings.append(
            "OpenStates data/us-shaped federal legacy profiles were refreshed this run."
        )

    status = "warning" if warnings else "passed"
    health = {"status": status, "checks": checks}
    if warnings:
        health["warnings"] = warnings

    summary.set_identity_health(**health)

    print("\n=== Identity health ===")
    print(f"status: {status}")
    for key, value in checks.items():
        print(f"  {key}: {value}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  {warning}")

    return health
