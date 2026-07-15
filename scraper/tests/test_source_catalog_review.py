import unittest

from etl_summary import ETLRunSummary
from source_catalog_review import run_source_catalog_review_check
from source_health import SourceHealthTracker


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.columns = None
        self.after_slug = None
        self.limit_value = None

    def select(self, columns):
        self.columns = columns
        return self

    def order(self, _column):
        return self

    def gt(self, column, value):
        if column == "slug":
            self.after_slug = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        self.client.queries.append(
            (self.table_name, self.after_slug, self.limit_value, self.columns)
        )
        rows = sorted(
            self.client.rows,
            key=lambda row: row.get("slug") or "",
        )
        if self.after_slug is not None:
            rows = [row for row in rows if (row.get("slug") or "") > self.after_slug]
        return FakeResponse(rows[: self.limit_value])


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def table(self, table_name):
        return FakeQuery(self, table_name)


class FakeLoader:
    def __init__(self, supabase, error=None):
        self.supabase = supabase
        self.error = error
        self.descriptions = []

    def execute_supabase(self, operation, description, retries=3):
        self.descriptions.append(description)
        if self.error:
            raise self.error
        return operation()


class SourceCatalogReviewTests(unittest.TestCase):
    def test_aggregates_private_worklist_without_source_identifiers(self):
        client = FakeSupabase(
            [
                {
                    "slug": "alpha",
                    "status": "candidate",
                    "review_focus": "official_source_review",
                    "latest_reviewed_at": None,
                },
                {
                    "slug": "bravo",
                    "status": "candidate",
                    "review_focus": "credential_and_quota_review",
                    "latest_reviewed_at": "2026-07-14T00:00:00Z",
                },
                {
                    "slug": "charlie",
                    "status": "blocked",
                    "review_focus": "official_source_review",
                    "latest_reviewed_at": "2026-07-14T00:00:00Z",
                },
                {
                    "slug": "delta",
                    "status": "deferred",
                    "review_focus": "general_source_review",
                    "latest_reviewed_at": None,
                },
                {
                    "slug": "echo",
                    "status": "duplicate",
                    "review_focus": "general_source_review",
                    "latest_reviewed_at": None,
                },
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_catalog_review", min_attempts_for_rate=1)

        result = run_source_catalog_review_check(
            FakeLoader(client),
            summary,
            health,
            page_size=2,
            max_items=10,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual(5, result["checks"]["source_catalog_review_worklist_items"])
        self.assertEqual(2, result["checks"]["source_catalog_review_candidate_items"])
        self.assertEqual(1, result["checks"]["source_catalog_review_blocked_items"])
        self.assertEqual(1, result["checks"]["source_catalog_review_deferred_items"])
        self.assertEqual(1, result["checks"]["source_catalog_review_duplicate_items"])
        self.assertEqual(1, result["checks"]["source_catalog_review_credential_items"])
        self.assertEqual(2, result["checks"]["source_catalog_review_official_source_items"])
        self.assertEqual(3, result["checks"]["source_catalog_review_unreviewed_items"])
        self.assertEqual("healthy", health.status)
        self.assertEqual(
            [
                (
                    "source_catalog_report_review_worklist",
                    None,
                    2,
                    "slug,status,review_focus,latest_reviewed_at",
                ),
                (
                    "source_catalog_report_review_worklist",
                    "bravo",
                    2,
                    "slug,status,review_focus,latest_reviewed_at",
                ),
                (
                    "source_catalog_report_review_worklist",
                    "delta",
                    2,
                    "slug,status,review_focus,latest_reviewed_at",
                ),
            ],
            client.queries,
        )
        serialized_summary = str(summary.as_dict(success=True))
        for slug in ("alpha", "bravo", "charlie", "delta", "echo"):
            self.assertNotIn(slug, serialized_summary)

    def test_marks_counts_partial_when_the_bounded_window_has_more_rows(self):
        client = FakeSupabase(
            [
                {"slug": "alpha", "status": "candidate", "review_focus": "general_source_review"},
                {"slug": "bravo", "status": "candidate", "review_focus": "general_source_review"},
                {"slug": "charlie", "status": "candidate", "review_focus": "general_source_review"},
                {"slug": "delta", "status": "candidate", "review_focus": "general_source_review"},
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_catalog_review", min_attempts_for_rate=1)

        result = run_source_catalog_review_check(
            FakeLoader(client),
            summary,
            health,
            page_size=2,
            max_items=3,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual(3, result["checks"]["source_catalog_review_worklist_items"])
        self.assertEqual(1, result["checks"]["source_catalog_review_worklist_capped"])
        self.assertEqual("degraded", health.status)
        self.assertEqual(1, health.skip_reasons["worklist_cap_reached"])

    def test_does_not_mark_an_exactly_full_window_as_capped(self):
        client = FakeSupabase(
            [
                {
                    "slug": "alpha",
                    "status": "candidate",
                    "review_focus": "general_source_review",
                },
                {
                    "slug": "bravo",
                    "status": "candidate",
                    "review_focus": "general_source_review",
                },
                {
                    "slug": "charlie",
                    "status": "candidate",
                    "review_focus": "general_source_review",
                },
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_catalog_review", min_attempts_for_rate=1)

        result = run_source_catalog_review_check(
            FakeLoader(client),
            summary,
            health,
            page_size=2,
            max_items=3,
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual(3, result["checks"]["source_catalog_review_worklist_items"])
        self.assertEqual(0, result["checks"]["source_catalog_review_worklist_capped"])
        self.assertEqual("healthy", health.status)

    def test_skips_cleanly_without_a_supabase_client(self):
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_catalog_review", min_attempts_for_rate=1)

        result = run_source_catalog_review_check(
            FakeLoader(None),
            summary,
            health,
        )

        self.assertEqual("skipped", result["status"])
        self.assertEqual("skipped", health.status)
        self.assertEqual(1, health.skip_reasons["supabase_not_configured"])

    def test_query_failure_is_visible_but_nonblocking(self):
        summary = ETLRunSummary()
        health = SourceHealthTracker(
            "source_catalog_review",
            min_attempts_for_rate=1,
            affects_run=False,
        )

        result = run_source_catalog_review_check(
            FakeLoader(FakeSupabase([]), error=RuntimeError("view missing")),
            summary,
            health,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual("failed", health.status)
        self.assertEqual(1, health.failure_reasons["query_error"])
        self.assertEqual([], summary.run_blocking_source_failures())


if __name__ == "__main__":
    unittest.main()
