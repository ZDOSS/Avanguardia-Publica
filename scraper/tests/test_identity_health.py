import importlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


class SummaryStub:
    def __init__(self):
        self.started_at = datetime(2026, 7, 7, 11, 1, tzinfo=timezone.utc)
        self.identity_health = None

    def set_identity_health(self, **payload):
        self.identity_health = payload


class FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = []
        self.like_filters = []
        self.gte_filters = []
        self.limit_count = None
        self.count_requested = False

    def select(self, _columns, count=None):
        self.count_requested = count == "exact"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def like(self, column, pattern):
        self.like_filters.append((column, pattern))
        return self

    def gte(self, column, value):
        self.gte_filters.append((column, value))
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def execute(self):
        rows = list(self.client.table_data.get(self.table_name, []))
        for column, value in self.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, pattern in self.like_filters:
            rows = [row for row in rows if self._matches_like(row.get(column), pattern)]
        for column, value in self.gte_filters:
            rows = [row for row in rows if str(row.get(column) or "") >= str(value)]

        total_count = len(rows)
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return FakeResponse(rows, count=total_count if self.count_requested else None)

    @staticmethod
    def _matches_like(value, pattern):
        value = str(value or "")
        if pattern.endswith("%"):
            return value.startswith(pattern[:-1])
        return value == pattern


class FakeSupabase:
    def __init__(self, table_data=None):
        self.table_data = table_data or {}

    def table(self, table_name):
        return FakeQuery(self, table_name)


class FakeLoader:
    def __init__(self, supabase):
        self.supabase = supabase
        self.descriptions = []

    def execute_supabase(self, operation, description, retries=3):
        self.descriptions.append(description)
        return operation()


class IdentityHealthTests(unittest.TestCase):
    def setUp(self):
        scraper_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(scraper_dir))
        sys.modules.pop("identity_health", None)
        self.identity_health = importlib.import_module("identity_health")

    def test_skips_without_supabase_client(self):
        summary = SummaryStub()
        loader = FakeLoader(None)

        health = self.identity_health.run_identity_health_check(loader, summary)

        self.assertEqual("skipped", health["status"])
        self.assertEqual("skipped", summary.identity_health["status"])
        self.assertEqual([], loader.descriptions)

    def test_passes_when_cleanup_stays_stable(self):
        summary = SummaryStub()
        loader = FakeLoader(
            FakeSupabase(
                {
                    "identity_resolution_candidates": [
                        {
                            "id": "candidate-1",
                            "candidate_type": self.identity_health.OPENSTATES_DUPLICATE_CANDIDATE_TYPE,
                            "status": "approved",
                        }
                    ],
                    "politicians": [
                        {
                            "id": "pol-1",
                            "current_office": "State Representative from US District CA-18",
                            "last_updated": "2026-07-07T04:30:23+00:00",
                        },
                        {
                            "id": "pol-2",
                            "current_office": "US Representative from CA-18",
                            "last_updated": "2026-07-07T12:30:14+00:00",
                        },
                    ],
                }
            )
        )

        health = self.identity_health.run_identity_health_check(loader, summary)

        self.assertEqual("passed", health["status"])
        self.assertEqual(0, health["checks"]["pending_identity_observer_candidates"])
        self.assertEqual(
            0,
            health["checks"]["pending_openstates_federal_duplicate_candidates"],
        )
        self.assertEqual(
            1,
            health["checks"]["approved_openstates_federal_duplicate_candidates"],
        )
        self.assertEqual(1, health["checks"]["openstates_federal_legacy_profiles_total"])
        self.assertEqual(
            0,
            health["checks"]["openstates_federal_legacy_profiles_refreshed_this_run"],
        )

    def test_warns_on_pending_candidates_and_refreshed_bad_profiles(self):
        summary = SummaryStub()
        loader = FakeLoader(
            FakeSupabase(
                {
                    "identity_resolution_candidates": [
                        {
                            "id": "candidate-1",
                            "candidate_type": self.identity_health.OPENSTATES_DUPLICATE_CANDIDATE_TYPE,
                            "status": "pending",
                        },
                        {
                            "id": "candidate-2",
                            "candidate_type": "identity_observer_pending_missing_deterministic_identity",
                            "status": "pending",
                        },
                    ],
                    "politicians": [
                        {
                            "id": "pol-1",
                            "current_office": "State Senator from US District Maryland",
                            "last_updated": "2026-07-07T11:10:10+00:00",
                        }
                    ],
                }
            )
        )

        health = self.identity_health.run_identity_health_check(loader, summary)

        self.assertEqual("warning", health["status"])
        self.assertEqual(2, health["checks"]["pending_identity_observer_candidates"])
        self.assertEqual(
            1,
            health["checks"]["pending_openstates_federal_duplicate_candidates"],
        )
        self.assertEqual(
            1,
            health["checks"]["openstates_federal_legacy_profiles_refreshed_this_run"],
        )
        self.assertEqual(3, len(health["warnings"]))


if __name__ == "__main__":
    unittest.main()
