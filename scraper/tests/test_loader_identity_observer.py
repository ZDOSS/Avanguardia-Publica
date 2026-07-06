import importlib
import sys
import types
import unittest
from pathlib import Path


class SummaryStub:
    def __init__(self):
        self.counts = {}

    def increment(self, key, amount=1):
        self.counts[key] = self.counts.get(key, 0) + amount


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, client, table_name=None, rpc_name=None, rpc_args=None):
        self.client = client
        self.table_name = table_name
        self.rpc_name = rpc_name
        self.rpc_args = rpc_args
        self.action = None
        self.payload = None
        self.filters = []
        self.contains_filters = []
        self.range_bounds = None

    def select(self, _columns):
        self.action = "select"
        return self

    def range(self, start, end):
        self.range_bounds = (start, end)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def contains(self, column, value):
        self.contains_filters.append((column, value))
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def execute(self):
        if self.rpc_name == "sync_legacy_profile_identity":
            politician_id = self.rpc_args["p_politician_id"]
            self.client.operations.append(
                {
                    "type": "rpc",
                    "name": self.rpc_name,
                    "args": self.rpc_args,
                }
            )
            return FakeResponse(
                [{"person_id": self.client.rpc_person_ids.get(politician_id, "person-new")}]
            )

        if self.action == "select":
            return FakeResponse(self.client.select_rows(self))

        if self.action == "update":
            self.client.operations.append(
                {
                    "type": "update",
                    "table": self.table_name,
                    "filters": list(self.filters),
                    "payload": self.payload,
                }
            )
            return FakeResponse([])

        if self.action == "insert":
            row = dict(self.payload)
            row.setdefault("id", self.client.next_insert_id)
            self.client.table_data.setdefault(self.table_name, []).append(row)
            self.client.operations.append(
                {
                    "type": "insert",
                    "table": self.table_name,
                    "payload": row,
                }
            )
            return FakeResponse([{"id": row["id"]}])

        return FakeResponse([])


class FakeSupabase:
    def __init__(self, table_data=None, rpc_person_ids=None):
        self.table_data = table_data or {}
        self.rpc_person_ids = rpc_person_ids or {}
        self.operations = []
        self.next_insert_id = "pol-new"

    def table(self, table_name):
        return FakeQuery(self, table_name=table_name)

    def rpc(self, rpc_name, args):
        return FakeQuery(self, rpc_name=rpc_name, rpc_args=args)

    def select_rows(self, query):
        rows = list(self.table_data.get(query.table_name, []))
        for column, value in query.filters:
            rows = [row for row in rows if row.get(column) == value]
        for column, value in query.contains_filters:
            rows = [row for row in rows if self._contains(row.get(column) or {}, value)]
        if query.range_bounds:
            start, end = query.range_bounds
            rows = rows[start : end + 1]
        return rows

    @staticmethod
    def _contains(existing, expected):
        return all(existing.get(key) == value for key, value in expected.items())


class LoaderIdentityObserverTests(unittest.TestCase):
    def setUp(self):
        self.scraper_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.scraper_dir))

        self.fake_client = FakeSupabase(
            table_data={
                "person_external_ids": [
                    {
                        "person_id": "person-1",
                        "source_system_key": "bioguide",
                        "external_id_type": "bioguide_id",
                        "external_id": "B000001",
                    }
                ],
                "legacy_profile_redirects": [
                    {
                        "person_id": "person-1",
                        "legacy_politician_id": "pol-1",
                    }
                ],
                "politicians": [
                    {
                        "id": "pol-1",
                        "full_name": "Jane Public",
                        "bioguide_id": "B000001",
                        "external_ids": {},
                    }
                ],
            },
            rpc_person_ids={"pol-1": "person-1", "pol-new": "person-new"},
        )
        supabase_stub = types.ModuleType("supabase")
        supabase_stub.create_client = lambda _url, _key: self.fake_client
        supabase_stub.Client = object
        sys.modules["supabase"] = supabase_stub
        sys.modules.pop("loader", None)
        self.loader_module = importlib.import_module("loader")

    def tearDown(self):
        sys.modules.pop("loader", None)
        sys.modules.pop("supabase", None)
        try:
            sys.path.remove(str(self.scraper_dir))
        except ValueError:
            pass

    def test_observer_loads_identity_snapshot_and_counts_match(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        resolution = loader.observe_politician_identity(
            "pol-1",
            {
                "full_name": "Jane Public",
                "bioguide_id": "B000001",
                "external_ids": {},
            },
        )

        self.assertEqual("matched_existing_person", resolution.action)
        self.assertEqual("person-1", resolution.person_id)
        self.assertEqual(1, summary.counts["identity_observer_people_loaded"])
        self.assertEqual(1, summary.counts["identity_observer_external_ids_loaded"])
        self.assertEqual(1, summary.counts["identity_observer_legacy_redirects_loaded"])
        self.assertEqual(1, summary.counts["identity_observer_packets_checked"])
        self.assertEqual(1, summary.counts["identity_observer_matched_existing_person"])

    def test_upsert_politician_runs_observer_without_extra_identity_writes(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        politician_id = loader.upsert_politician(
            {
                "full_name": "Jane Public",
                "current_office": "US Representative",
                "bioguide_id": "B000001",
                "external_ids": {},
                "aliases": [],
            }
        )

        self.assertEqual("pol-1", politician_id)
        self.assertEqual(1, summary.counts["hub_rows_updated"])
        self.assertEqual(1, summary.counts["identity_observer_packets_checked"])
        self.assertEqual(1, summary.counts["identity_observer_matched_existing_person"])
        operation_types = [(item["type"], item.get("table") or item.get("name")) for item in self.fake_client.operations]
        self.assertEqual(
            [
                ("update", "politicians"),
                ("rpc", "sync_legacy_profile_identity"),
            ],
            operation_types,
        )

    def test_observer_refreshes_snapshot_after_sync_for_later_packets(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        loader.observe_politician_identity(
            "pol-new",
            {
                "full_name": "New Person",
                "bioguide_id": "B000999",
                "external_ids": {},
            },
        )

        loader._record_identity_observer_mapping(
            "pol-new",
            {
                "full_name": "New Person",
                "bioguide_id": "B000999",
                "external_ids": {},
            },
            "person-new",
        )
        resolution = loader.observe_politician_identity(
            "pol-later",
            {
                "full_name": "New Person",
                "bioguide_id": "B000999",
                "external_ids": {},
            },
        )

        self.assertEqual("matched_existing_person", resolution.action)
        self.assertEqual("person-new", resolution.person_id)
        self.assertEqual(1, summary.counts["identity_observer_create_person"])
        self.assertEqual(1, summary.counts["identity_observer_matched_existing_person"])


if __name__ == "__main__":
    unittest.main()
