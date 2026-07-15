"""Aggregate-only health for the private source-catalog review worklist.

The worklist itself remains service-role-only.  This module reads a bounded window
through the scraper's service client and emits only counts, never source names,
URLs, review evidence, or credentials into the ETL summary.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from source_health import SourceHealthTracker


logger = logging.getLogger(__name__)

_WORKLIST_VIEW = "source_catalog_report_review_worklist"
_WORKLIST_COLUMNS = "slug,status,review_focus,latest_reviewed_at"
_PAGE_SIZE = 100
_MAX_WORKLIST_ITEMS = 500


@dataclass(frozen=True)
class SourceCatalogReviewReport:
    """Non-identifying aggregate of the private source-review queue."""

    worklist_items: int = 0
    candidate_items: int = 0
    deferred_items: int = 0
    blocked_items: int = 0
    duplicate_items: int = 0
    credential_review_items: int = 0
    official_source_review_items: int = 0
    unreviewed_items: int = 0
    worklist_capped: bool = False

    def checks(self) -> dict[str, int]:
        """Stable ETL-summary field names without private worklist identities."""
        return {
            "source_catalog_review_worklist_items": self.worklist_items,
            "source_catalog_review_candidate_items": self.candidate_items,
            "source_catalog_review_deferred_items": self.deferred_items,
            "source_catalog_review_blocked_items": self.blocked_items,
            "source_catalog_review_duplicate_items": self.duplicate_items,
            "source_catalog_review_credential_items": self.credential_review_items,
            "source_catalog_review_official_source_items": (
                self.official_source_review_items
            ),
            "source_catalog_review_unreviewed_items": self.unreviewed_items,
            "source_catalog_review_worklist_capped": int(self.worklist_capped),
        }

def _normalized_text(value) -> str:
    return str(value or "").strip().lower()


def _load_worklist_rows(
    loader,
    *,
    page_size: int,
    max_items: int,
) -> tuple[list[dict], bool]:
    """Read the bounded private view with keyset pagination on its unique slug."""
    if page_size < 1 or max_items < 1:
        raise ValueError("source catalog review page_size and max_items must be positive")

    rows: list[dict] = []
    after_slug: str | None = None

    while True:
        # When the configured window is full, fetch one more row to distinguish an
        # exact fit from a truncated worklist without using OFFSET pagination.
        fetch_limit = (
            1
            if len(rows) >= max_items
            else min(page_size, max_items - len(rows))
        )

        def operation(after_slug=after_slug, fetch_limit=fetch_limit):
            query = (
                loader.supabase.table(_WORKLIST_VIEW)
                .select(_WORKLIST_COLUMNS)
                .order("slug")
                .limit(fetch_limit)
            )
            if after_slug is not None:
                query = query.gt("slug", after_slug)
            return query.execute()

        response = loader.execute_supabase(
            operation,
            "source catalog review worklist aggregate",
        )
        batch = response.data or []
        if not batch:
            return rows, False
        if len(rows) >= max_items:
            return rows, True

        previous_slug = after_slug
        for row in batch:
            if not isinstance(row, dict):
                raise ValueError("source catalog review worklist row is not an object")
            slug = str(row.get("slug") or "").strip()
            if not slug or (previous_slug is not None and slug <= previous_slug):
                raise ValueError("source catalog review worklist has invalid slug ordering")
            previous_slug = slug

        rows.extend(batch)
        after_slug = previous_slug
        if len(batch) < fetch_limit:
            return rows, False


def _aggregate(rows: list[dict], worklist_capped: bool) -> SourceCatalogReviewReport:
    counts = {
        "candidate": 0,
        "deferred": 0,
        "blocked": 0,
        "duplicate": 0,
        "credential": 0,
        "official": 0,
        "unreviewed": 0,
    }
    for row in rows:
        status = _normalized_text(row.get("status"))
        if status in ("candidate", "deferred", "blocked", "duplicate"):
            counts[status] += 1
        review_focus = _normalized_text(row.get("review_focus"))
        if review_focus == "credential_and_quota_review":
            counts["credential"] += 1
        if review_focus == "official_source_review":
            counts["official"] += 1
        if not row.get("latest_reviewed_at"):
            counts["unreviewed"] += 1

    return SourceCatalogReviewReport(
        worklist_items=len(rows),
        candidate_items=counts["candidate"],
        deferred_items=counts["deferred"],
        blocked_items=counts["blocked"],
        duplicate_items=counts["duplicate"],
        credential_review_items=counts["credential"],
        official_source_review_items=counts["official"],
        unreviewed_items=counts["unreviewed"],
        worklist_capped=worklist_capped,
    )


def _set_summary(summary, status: str, report: SourceCatalogReviewReport, warnings=None):
    summary.set_source_catalog_review(
        status,
        checks=report.checks(),
        warnings=warnings,
    )


def run_source_catalog_review_check(
    loader,
    summary,
    health: SourceHealthTracker,
    *,
    page_size: int = _PAGE_SIZE,
    max_items: int = _MAX_WORKLIST_ITEMS,
) -> dict:
    """Summarize the private review queue without making it an ETL failure path."""
    empty_report = SourceCatalogReviewReport()
    if not loader.supabase:
        health.record_skip("supabase_not_configured")
        warning = "Source catalog review check skipped: Supabase client is not configured."
        _set_summary(summary, "skipped", empty_report, [warning])
        print("\n=== Source catalog review ===")
        print("status: skipped")
        print(f"  {warning}")
        return summary.source_catalog_review

    health.record_attempt()
    started_at = time.monotonic()
    try:
        rows, worklist_capped = _load_worklist_rows(
            loader,
            page_size=page_size,
            max_items=max_items,
        )
    except Exception:
        # The worklist is private. Keep query details out of routine ETL logs and
        # leave the non-identifying failure reason in source health instead.
        logger.warning("Source catalog review worklist query failed.")
        health.record_failure("query_error", time.monotonic() - started_at)
        warning = "Source catalog review check failed; inspect source health for details."
        _set_summary(summary, "warning", empty_report, [warning])
        print("\n=== Source catalog review ===")
        print("status: warning")
        print(f"  {warning}")
        return summary.source_catalog_review

    health.record_success(time.monotonic() - started_at)
    if worklist_capped:
        health.record_skip("worklist_cap_reached")
    report = _aggregate(rows, worklist_capped)
    warnings = []
    if report.blocked_items:
        warnings.append("Source catalog contains blocked review items.")
    if report.worklist_capped:
        warnings.append(
            "Source catalog worklist exceeded its bounded aggregate scan; counts are partial."
        )
    status = "warning" if warnings else "passed"
    _set_summary(summary, status, report, warnings)

    print("\n=== Source catalog review ===")
    print(f"status: {status}")
    for key, value in report.checks().items():
        print(f"  {key}: {value}")
    for warning in warnings:
        print(f"warning: {warning}")
    return summary.source_catalog_review
