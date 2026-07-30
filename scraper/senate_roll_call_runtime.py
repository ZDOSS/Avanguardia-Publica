"""Fail-closed runtime controls for official Senate roll-call writes."""

from __future__ import annotations

from collections.abc import Mapping


SENATE_ROLL_CALL_WRITE_MODE_ENV = "SENATE_ROLL_CALL_WRITE_MODE"
SENATE_ROLL_CALL_WRITE_DISABLED = "disabled"
SENATE_ROLL_CALL_WRITE_ENABLED = "enabled"


def senate_roll_call_write_mode(environ: Mapping[str, str]) -> str:
    """Return the explicit runtime mode, rejecting ambiguous opt-in values."""
    mode = str(environ.get(SENATE_ROLL_CALL_WRITE_MODE_ENV) or "").strip().lower()
    mode = mode or SENATE_ROLL_CALL_WRITE_DISABLED
    if mode not in {SENATE_ROLL_CALL_WRITE_DISABLED, SENATE_ROLL_CALL_WRITE_ENABLED}:
        raise ValueError(
            f"{SENATE_ROLL_CALL_WRITE_MODE_ENV} must be 'disabled' or 'enabled'"
        )
    return mode


def write_senate_roll_calls(
    loader, report, fetch_health, write_health, *, mode: str
) -> int:
    """Write an already-fetched bounded snapshot only when explicitly enabled."""
    if mode == SENATE_ROLL_CALL_WRITE_DISABLED:
        write_health.record_skip("runtime_mode_disabled")
        return 0
    if mode != SENATE_ROLL_CALL_WRITE_ENABLED:
        raise ValueError(f"unsupported Senate roll-call write mode: {mode}")

    try:
        return _write_enabled_senate_roll_calls(
            loader, report, fetch_health, write_health
        )
    except Exception:
        if not write_health.breaker_tripped:
            write_health.record_attempt()
            write_health.trip_breaker("unexpected_write_error")
            write_health.record_failure("unexpected_write_error")
        raise


def _write_enabled_senate_roll_calls(
    loader, report, fetch_health, write_health
) -> int:
    """Apply eligibility checks and write one atomic RPC per complete roll call."""
    if (
        report.snapshot_complete
        and not report.roll_calls
        and fetch_health.failures == 0
        and not fetch_health.breaker_tripped
    ):
        write_health.record_skip("no_current_session_roll_calls")
        return 0

    block_reasons = list(report.authoritative_write_block_reasons(fetch_health))
    if loader.supabase is None:
        block_reasons.append("supabase_not_configured")
    if block_reasons:
        write_health.record_attempt()
        for reason in dict.fromkeys(block_reasons):
            write_health.record_skip(reason)
        write_health.trip_breaker("write_preconditions_not_met")
        write_health.record_failure("write_preconditions_not_met")
        return 0

    written = 0
    for roll_call in report.roll_calls:
        write_health.record_attempt()
        try:
            roll_call_payload, member_votes = roll_call.rpc_payload()
            loader.upsert_senate_roll_call(roll_call_payload, member_votes)
        except Exception:
            write_health.trip_breaker("rpc_write_failed")
            write_health.record_failure("rpc_write_failed")
            raise
        write_health.record_success()
        written += 1
    return written
