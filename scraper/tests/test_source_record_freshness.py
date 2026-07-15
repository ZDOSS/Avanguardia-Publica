from datetime import datetime, timezone
import unittest

from etl_summary import ETLRunSummary
from source_health import SourceHealthTracker
from source_record_freshness import run_source_record_freshness_check


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.columns = None
        self.record_status = None
        self.cutoff = None
        self.order_column = None
        self.order_desc = False
        self.limit_value = None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        if column == "record_status":
            self.record_status = value
        return self

    def lt(self, column, value):
        if column == "last_seen_at":
            self.cutoff = value
        return self

    def order(self, column, desc=False):
        self.order_column = column
        self.order_desc = desc
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        self.client.queries.append(
            (
                self.table_name,
                self.columns,
                self.record_status,
                self.cutoff,
                self.order_column,
                self.order_desc,
                self.limit_value,
            )
        )
        rows = self.client.rows
        if self.record_status is not None:
            rows = [row for row in rows if row.get("record_status") == self.record_status]
        if self.cutoff is not None:
            rows = [row for row in rows if row.get("last_seen_at", "") < self.cutoff]
        rows = sorted(
            rows,
            key=lambda row: row.get(self.order_column) or "",
            reverse=self.order_desc,
        )
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


class SourceRecordFreshnessTests(unittest.TestCase):
    NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)

    def test_reports_stale_active_records_without_record_identifiers(self):
        stale_id = "private-stale-record"
        client = FakeSupabase(
            [
                {
                    "id": stale_id,
                    "record_status": "active",
                    "last_seen_at": "2026-06-30T00:00:00+00:00",
                },
                {
                    "id": "private-fresh-record",
                    "record_status": "active",
                    "last_seen_at": "2026-07-14T00:00:00+00:00",
                },
                {
                    "id": "private-retired-record",
                    "record_status": "retired",
                    "last_seen_at": "2026-06-01T00:00:00+00:00",
                },
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_record_freshness", min_attempts_for_rate=1)

        result = run_source_record_freshness_check(
            FakeLoader(client),
            summary,
            health,
            now=self.NOW,
            stale_after_days=14,
            max_records=10,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual(
            1, result["checks"]["source_record_freshness_stale_active_records"]
        )
        self.assertEqual(14, result["checks"]["source_record_freshness_threshold_days"])
        self.assertEqual(0, result["checks"]["source_record_freshness_stale_records_capped"])
        self.assertEqual("healthy", health.status)
        self.assertEqual(
            [
                (
                    "source_records",
                    "id,last_seen_at",
                    "active",
                    "2026-07-01T00:00:00+00:00",
                    "last_seen_at",
                    True,
                    11,
                )
            ],
            client.queries,
        )
        serialized_summary = str(summary.as_dict(success=True))
        for record_id in (
            stale_id,
            "private-fresh-record",
            "private-retired-record",
        ):
            self.assertNotIn(record_id, serialized_summary)

    def test_marks_counts_partial_when_stale_records_exceed_bounded_window(self):
        client = FakeSupabase(
            [
                {
                    "id": f"private-{index}",
                    "record_status": "active",
                    "last_seen_at": f"2026-06-0{index}T00:00:00+00:00",
                }
                for index in range(1, 5)
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_record_freshness", min_attempts_for_rate=1)

        result = run_source_record_freshness_check(
            FakeLoader(client),
            summary,
            health,
            now=self.NOW,
            max_records=3,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual(
            3, result["checks"]["source_record_freshness_stale_active_records"]
        )
        self.assertEqual(1, result["checks"]["source_record_freshness_stale_records_capped"])
        self.assertEqual("degraded", health.status)
        self.assertEqual(1, health.skip_reasons["stale_record_cap_reached"])

    def test_passes_when_no_active_records_are_stale(self):
        client = FakeSupabase(
            [
                {
                    "id": "private-fresh-record",
                    "record_status": "active",
                    "last_seen_at": "2026-07-14T00:00:00+00:00",
                }
            ]
        )
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_record_freshness", min_attempts_for_rate=1)

        result = run_source_record_freshness_check(
            FakeLoader(client), summary, health, now=self.NOW
        )

        self.assertEqual("passed", result["status"])
        self.assertEqual(
            0, result["checks"]["source_record_freshness_stale_active_records"]
        )
        self.assertEqual("healthy", health.status)

    def test_skips_cleanly_without_a_supabase_client(self):
        summary = ETLRunSummary()
        health = SourceHealthTracker("source_record_freshness", min_attempts_for_rate=1)

        result = run_source_record_freshness_check(FakeLoader(None), summary, health)

        self.assertEqual("skipped", result["status"])
        self.assertEqual("skipped", health.status)
        self.assertEqual(1, health.skip_reasons["supabase_not_configured"])

    def test_query_failure_is_visible_but_nonblocking(self):
        summary = ETLRunSummary()
        health = SourceHealthTracker(
            "source_record_freshness", min_attempts_for_rate=1, affects_run=False
        )

        result = run_source_record_freshness_check(
            FakeLoader(FakeSupabase([]), error=RuntimeError("private table missing")),
            summary,
            health,
            now=self.NOW,
        )

        self.assertEqual("warning", result["status"])
        self.assertEqual("failed", health.status)
        self.assertEqual(1, health.failure_reasons["query_error"])
        self.assertEqual([], summary.run_blocking_source_failures())


if __name__ == "__main__":
    unittest.main()
