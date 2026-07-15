"""Aggregate-only freshness health for private source records.

The service-role-only ``source_records`` table stores provenance for canonical
profile writes. This module reports whether active records have not been seen
within a bounded freshness window, without emitting record IDs, names, URLs, or
payload references into the ETL summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time

from source_health import SourceHealthTracker


logger = logging.getLogger(__name__)

_SOURCE_RECORDS_TABLE = "source_records"
_SOURCE_RECORDS_COLUMNS = "id,last_seen_at"
_STALE_AFTER_DAYS = 14
_MAX_STALE_RECORDS = 500


@dataclass(frozen=True)
class SourceRecordFreshnessReport:
    """Non-identifying aggregate of active source records past the freshness window."""

    stale_active_records: int = 0
    stale_after_days: int = _STALE_AFTER_DAYS
    stale_records_capped: bool = False

    def checks(self) -> dict[str, int]:
        """Stable ETL-summary fields that do not reveal private source records."""
        return {
            "source_record_freshness_stale_active_records": self.stale_active_records,
            "source_record_freshness_threshold_days": self.stale_after_days,
            "source_record_freshness_stale_records_capped": int(self.stale_records_capped),
        }


def _as_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("source record freshness clock must be timezone-aware")
    return now.astimezone(timezone.utc)


def _load_stale_active_records(
    loader,
    *,
    cutoff: datetime,
    max_records: int,
) -> tuple[list[dict], bool]:
    """Read at most one bounded stale-record window plus a truncation sentinel.

    The query follows ``idx_source_records_status_last_seen`` from migration 0022:
    it filters active records and orders by ``last_seen_at``. The returned IDs are
    used only to count rows locally and never leave this module.
    """
    if max_records < 1:
        raise ValueError("source record freshness max_records must be positive")

    response = loader.execute_supabase(
        lambda: (
            loader.supabase.table(_SOURCE_RECORDS_TABLE)
            .select(_SOURCE_RECORDS_COLUMNS)
            .eq("record_status", "active")
            .lt("last_seen_at", cutoff.isoformat())
            .order("last_seen_at", desc=True)
            .limit(max_records + 1)
            .execute()
        ),
        "source record freshness aggregate",
    )
    rows = response.data or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("source record freshness query returned invalid rows")
    return rows[:max_records], len(rows) > max_records


def _set_summary(
    summary,
    status: str,
    report: SourceRecordFreshnessReport,
    warnings: list[str] | None = None,
) -> None:
    summary.set_source_record_freshness(
        status,
        checks=report.checks(),
        warnings=warnings,
    )


def run_source_record_freshness_check(
    loader,
    summary,
    health: SourceHealthTracker,
    *,
    stale_after_days: int = _STALE_AFTER_DAYS,
    max_records: int = _MAX_STALE_RECORDS,
    now: datetime | None = None,
) -> dict:
    """Report stale active provenance records without changing ETL success semantics."""
    if stale_after_days < 1:
        raise ValueError("source record freshness stale_after_days must be positive")

    empty_report = SourceRecordFreshnessReport(stale_after_days=stale_after_days)
    if not loader.supabase:
        health.record_skip("supabase_not_configured")
        warning = "Source record freshness check skipped: Supabase client is not configured."
        _set_summary(summary, "skipped", empty_report, [warning])
        print("\n=== Source record freshness ===")
        print("status: skipped")
        print(f"  {warning}")
        return summary.source_record_freshness

    health.record_attempt()
    started_at = time.monotonic()
    cutoff = _as_utc(now) - timedelta(days=stale_after_days)
    try:
        rows, stale_records_capped = _load_stale_active_records(
            loader,
            cutoff=cutoff,
            max_records=max_records,
        )
    except Exception:
        # Source-record provenance is private. Keep raw query details out of normal
        # ETL logs and retain the non-identifying failure reason in source health.
        logger.warning("Source record freshness query failed.")
        health.record_failure("query_error", time.monotonic() - started_at)
        warning = "Source record freshness check failed; inspect source health for details."
        _set_summary(summary, "warning", empty_report, [warning])
        print("\n=== Source record freshness ===")
        print("status: warning")
        print(f"  {warning}")
        return summary.source_record_freshness

    health.record_success(time.monotonic() - started_at)
    if stale_records_capped:
        health.record_skip("stale_record_cap_reached")

    report = SourceRecordFreshnessReport(
        stale_active_records=len(rows),
        stale_after_days=stale_after_days,
        stale_records_capped=stale_records_capped,
    )
    warnings = []
    if report.stale_active_records:
        warnings.append(
            "Active source records have not been observed within the freshness window."
        )
    if report.stale_records_capped:
        warnings.append(
            "Source-record freshness scan exceeded its bounded window; counts are partial."
        )
    status = "warning" if warnings else "passed"
    _set_summary(summary, status, report, warnings)

    print("\n=== Source record freshness ===")
    print(f"status: {status}")
    for key, value in report.checks().items():
        print(f"  {key}: {value}")
    for warning in warnings:
        print(f"warning: {warning}")
    return summary.source_record_freshness
