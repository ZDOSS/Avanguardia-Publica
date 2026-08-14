"""Fail-closed runtime controls for private Congress.gov metadata writes."""

from __future__ import annotations

from collections.abc import Mapping


CONGRESS_GOV_METADATA_WRITE_MODE_ENV = "CONGRESS_GOV_METADATA_WRITE_MODE"
CONGRESS_GOV_METADATA_WRITE_DISABLED = "disabled"
CONGRESS_GOV_METADATA_WRITE_ENABLED = "enabled"


def congress_gov_metadata_write_mode(environ: Mapping[str, str]) -> str:
    """Return the explicit runtime mode, rejecting ambiguous opt-in values."""

    mode = str(environ.get(CONGRESS_GOV_METADATA_WRITE_MODE_ENV) or "").strip().lower()
    mode = mode or CONGRESS_GOV_METADATA_WRITE_DISABLED
    if mode not in {
        CONGRESS_GOV_METADATA_WRITE_DISABLED,
        CONGRESS_GOV_METADATA_WRITE_ENABLED,
    }:
        raise ValueError(
            f"{CONGRESS_GOV_METADATA_WRITE_MODE_ENV} must be 'disabled' or 'enabled'"
        )
    return mode


def write_congress_gov_metadata(
    loader,
    report,
    fetch_health,
    write_health,
    *,
    mode: str,
    upstream_snapshots_complete: bool,
    upstream_roll_call_count: int,
) -> tuple[int, int]:
    """Atomically write one complete bounded report only when explicitly enabled."""

    if mode == CONGRESS_GOV_METADATA_WRITE_DISABLED:
        write_health.record_skip("runtime_mode_disabled")
        return 0, 0
    if mode != CONGRESS_GOV_METADATA_WRITE_ENABLED:
        raise ValueError(f"unsupported Congress.gov metadata write mode: {mode}")

    try:
        return _write_enabled_congress_gov_metadata(
            loader,
            report,
            fetch_health,
            write_health,
            upstream_snapshots_complete=upstream_snapshots_complete,
            upstream_roll_call_count=upstream_roll_call_count,
        )
    except Exception:
        if not write_health.breaker_tripped:
            write_health.record_attempt()
            write_health.trip_breaker("unexpected_write_error")
            write_health.record_failure("unexpected_write_error")
        raise


def _write_enabled_congress_gov_metadata(
    loader,
    report,
    fetch_health,
    write_health,
    *,
    upstream_snapshots_complete: bool,
    upstream_roll_call_count: int,
) -> tuple[int, int]:
    if (
        upstream_snapshots_complete is True
        and report is not None
        and report.distinct_references == 0
        and isinstance(upstream_roll_call_count, int)
        and not isinstance(upstream_roll_call_count, bool)
        and upstream_roll_call_count >= 0
        and report.roll_calls_seen == upstream_roll_call_count
        and report.references_fetched == 0
        and report.references_not_fetched == 0
        and report.reference_links_seen == 0
        and not report.metadata
        and not report.roll_call_keys_by_reference
        and fetch_health.attempts == 0
        and fetch_health.successes == 0
        and fetch_health.failures == 0
        and not fetch_health.breaker_tripped
    ):
        write_health.record_skip("no_supported_measure_references")
        return 0, 0

    block_reasons = []
    measures = None
    links = None
    if upstream_snapshots_complete is not True:
        block_reasons.append("official_roll_call_snapshots_incomplete")
    if (
        isinstance(upstream_roll_call_count, bool)
        or not isinstance(upstream_roll_call_count, int)
        or upstream_roll_call_count < 0
    ):
        block_reasons.append("invalid_upstream_roll_call_count")
    if report is None:
        block_reasons.append("metadata_snapshot_unavailable")
    else:
        if report.roll_calls_seen != upstream_roll_call_count:
            block_reasons.append("roll_call_scope_mismatch")
        if not report.complete:
            block_reasons.append("incomplete_metadata_snapshot")
        if fetch_health.failures or fetch_health.breaker_tripped:
            block_reasons.append("source_health_not_healthy")
        if (
            fetch_health.attempts != report.distinct_references
            or fetch_health.successes != report.references_fetched
        ):
            block_reasons.append("source_health_reconciliation_mismatch")
        try:
            measures, links = report.rpc_payload()
        except ValueError:
            block_reasons.append("invalid_write_payload")
    if loader.supabase is None:
        block_reasons.append("supabase_not_configured")

    if block_reasons:
        write_health.record_attempt()
        for reason in dict.fromkeys(block_reasons):
            write_health.record_skip(reason)
        write_health.trip_breaker("write_preconditions_not_met")
        write_health.record_failure("write_preconditions_not_met")
        return 0, 0

    write_health.record_attempt()
    try:
        result = loader.upsert_congress_gov_measure_metadata(measures, links)
    except Exception:
        write_health.trip_breaker("rpc_write_failed")
        write_health.record_failure("rpc_write_failed")
        raise
    write_health.record_success()
    return int(result["measure_count"]), int(result["roll_call_link_count"])
