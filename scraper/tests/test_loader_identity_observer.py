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
        self.like_filters = []
        self.is_filters = []
        self.range_bounds = None
        self.limit_count = None

    def select(self, _columns):
        self.action = "select"
        return self

    def range(self, start, end):
        self.range_bounds = (start, end)
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def contains(self, column, value):
        self.contains_filters.append((column, value))
        return self

    def like(self, column, value):
        self.like_filters.append((column, value))
        return self

    def is_(self, column, value):
        self.is_filters.append((column, value))
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
        if self.rpc_name == "retire_source_profile_record":
            source_record_id = self.rpc_args["p_source_record_id"]
            source_row = next(
                row
                for row in self.client.table_data.get("source_records", [])
                if row.get("id") == source_record_id
            )
            retired_terms = 0
            for term in self.client.table_data.get("person_office_terms", []):
                if (
                    term.get("source_record_id") == source_record_id
                    and term.get("term_status") == "current"
                ):
                    term["term_status"] = "historical"
                    term["term_end"] = self.rpc_args["p_term_end"]
                    retired_terms += 1
            source_row["record_status"] = "retired"
            source_row["retired_at"] = self.rpc_args["p_retired_at"]
            self.client.operations.append(
                {"type": "rpc", "name": self.rpc_name, "args": self.rpc_args}
            )
            return FakeResponse(
                [
                    {
                        "source_record_id": source_record_id,
                        "person_id": source_row.get("person_id"),
                        "retired_office_term_count": retired_terms,
                        "record_status": "retired",
                    }
                ]
            )
        if self.rpc_name == "upsert_source_profile_identity":
            self.client.operations.append(
                {"type": "rpc", "name": self.rpc_name, "args": self.rpc_args}
            )
            key = (
                self.rpc_args["p_source_system_key"],
                self.rpc_args["p_source_record_key"],
            )
            result = self.client.source_rpc_results.get(
                key,
                {
                    "person_id": "person-new",
                    "legacy_politician_id": "pol-new",
                    "source_record_id": "source-record-1",
                    "office_term_id": "office-term-1",
                    "resolution_action": "created_person",
                },
            )
            return FakeResponse([result])
        if self.rpc_name == "sync_legacy_profile_identity":
            politician_id = self.rpc_args["p_politician_id"]
            person_id = self.client.rpc_person_ids.get(politician_id, "person-new")
            self.client.sync_identity(politician_id, person_id)
            self.client.operations.append(
                {
                    "type": "rpc",
                    "name": self.rpc_name,
                    "args": self.rpc_args,
                }
            )
            return FakeResponse([{"person_id": person_id}])

        if self.action == "select":
            return FakeResponse(self.client.select_rows(self))

        if self.action == "update":
            updated_rows = self.client.update_rows(self)
            self.client.operations.append(
                {
                    "type": "update",
                    "table": self.table_name,
                    "filters": list(self.filters),
                    "payload": self.payload,
                }
            )
            return FakeResponse(updated_rows)

        if self.action == "insert":
            row = dict(self.payload)
            table_rows = self.client.table_data.setdefault(self.table_name, [])
            if self.table_name == "politicians":
                row.setdefault("id", self.client.next_insert_id)
            else:
                row.setdefault("id", f"{self.table_name}-{len(table_rows) + 1}")
            table_rows.append(row)
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
    def __init__(self, table_data=None, rpc_person_ids=None, source_rpc_results=None):
        self.table_data = table_data or {}
        self.rpc_person_ids = rpc_person_ids or {}
        self.operations = []
        self.next_insert_id = "pol-new"
        self.source_rpc_results = source_rpc_results or {}

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
        for column, pattern in query.like_filters:
            prefix = pattern[:-1] if pattern.endswith("%") else pattern
            rows = [row for row in rows if str(row.get(column) or "").startswith(prefix)]
        for column, value in query.is_filters:
            if value == "null":
                rows = [row for row in rows if row.get(column) is None]
        if query.range_bounds:
            start, end = query.range_bounds
            rows = rows[start : end + 1]
        if query.limit_count is not None:
            rows = rows[: query.limit_count]
        return rows

    @classmethod
    def _contains(cls, existing, expected):
        if isinstance(expected, dict):
            return isinstance(existing, dict) and all(
                key in existing and cls._contains(existing[key], value)
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            return isinstance(existing, list) and all(
                any(cls._contains(item, wanted) for item in existing)
                for wanted in expected
            )
        return existing == expected

    def update_rows(self, query):
        updated_rows = []
        for row in self.table_data.get(query.table_name, []):
            if all(row.get(column) == value for column, value in query.filters):
                row.update(query.payload)
                updated_rows.append(dict(row))
        return updated_rows

    def sync_identity(self, politician_id, person_id):
        redirects = self.table_data.setdefault("legacy_profile_redirects", [])
        if not any(row.get("legacy_politician_id") == politician_id for row in redirects):
            redirects.append(
                {
                    "person_id": person_id,
                    "legacy_politician_id": politician_id,
                }
            )

        politicians = self.table_data.setdefault("politicians", [])
        politician = next((row for row in politicians if row.get("id") == politician_id), None)
        if not politician or not politician.get("bioguide_id"):
            return

        external_ids = self.table_data.setdefault("person_external_ids", [])
        identity_row = {
            "person_id": person_id,
            "source_system_key": "bioguide",
            "external_id_type": "bioguide_id",
            "external_id": politician["bioguide_id"],
        }
        if not any(
            row.get("source_system_key") == identity_row["source_system_key"]
            and row.get("external_id_type") == identity_row["external_id_type"]
            and str(row.get("external_id") or "").strip() == identity_row["external_id"]
            for row in external_ids
        ):
            external_ids.append(identity_row)


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
                        "external_id": " B000001 ",
                        "is_trusted": True,
                    }
                ],
                "people": [{"id": "person-1", "status": "active"}],
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

    def use_conflicting_identity_snapshot(self):
        self.fake_client.table_data["people"] = [
            {"id": "person-1", "status": "active"},
            {"id": "person-2", "status": "active"},
        ]
        self.fake_client.table_data["person_external_ids"] = [
            {
                "person_id": "person-1",
                "source_system_key": "bioguide",
                "external_id_type": "bioguide_id",
                "external_id": "B000001",
                "is_trusted": True,
            },
            {
                "person_id": "person-2",
                "source_system_key": "fec",
                "external_id_type": "fec_candidate_id",
                "external_id": "H0CA00001",
                "is_trusted": True,
            },
        ]
        self.fake_client.table_data["legacy_profile_redirects"] = []

    def observe_conflicting_identity(self, loader):
        return loader.observe_politician_identity(
            "pol-conflict",
            {
                "full_name": "Jane Conflict",
                "current_office": "US Representative",
                "bioguide_id": "B000001",
                "external_ids": {"fec": "H0CA00001"},
            },
        )

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

    def test_source_profile_uses_atomic_identity_rpc(self):
        self.fake_client.table_data["person_external_ids"] = []
        self.fake_client.table_data["legacy_profile_redirects"] = []
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        politician_id = loader.upsert_politician(
            {
                "full_name": "Alex State",
                "current_office": "State Representative from CA District 4",
                "party": "Independent",
                "state": "CA",
                "district": "4",
                "external_ids": {"openstates": "ocd-person/alex"},
                "aliases": ["Alex State"],
                "source_system_key": "openstates",
                "source_record_key": "ocd-person/alex",
                "source_catalog_slug": "openstates",
                "source_endpoint_slug": "people-tarball",
                "source_url": "https://example.test/alex",
                "raw_payload_ref": "data/ca/alex.yml",
                "source_updated_at": "2026-07-08T12:00:00Z",
                "verified_lane": "mixed",
                "source_term_key": "lower:4:2025-01-01",
                "term_start": "2025-01-01",
                "term_status": "current",
            }
        )

        self.assertEqual("pol-new", politician_id)
        self.assertEqual(
            [("rpc", "upsert_source_profile_identity")],
            [(item["type"], item.get("name")) for item in self.fake_client.operations],
        )
        args = self.fake_client.operations[0]["args"]
        self.assertEqual("openstates", args["p_source_system_key"])
        self.assertEqual("ocd-person/alex", args["p_source_record_key"])
        self.assertEqual("openstates", args["p_source_catalog_slug"])
        self.assertEqual("people-tarball", args["p_source_endpoint_slug"])
        self.assertEqual("2026-07-08T12:00:00Z", args["p_source_updated_at"])
        self.assertEqual(
            "lower:4:2025-01-01", args["p_office_term"]["source_term_key"]
        )

    def test_congress_and_executive_roles_share_person_but_keep_source_profiles_separate(self):
        self.fake_client.table_data["person_external_ids"] = []
        self.fake_client.table_data["legacy_profile_redirects"] = []
        self.fake_client.source_rpc_results = {
            ("congress-legislators", "B000321"): {
                "person_id": "person-shared",
                "legacy_politician_id": "pol-congress",
                "source_record_id": "source-congress",
                "office_term_id": "term-congress",
                "resolution_action": "created_person",
            },
            ("congress-legislators", "executive:Q321"): {
                "person_id": "person-shared",
                "legacy_politician_id": "pol-executive",
                "source_record_id": "source-executive",
                "office_term_id": "term-executive",
                "resolution_action": "matched_existing_person",
            },
        }
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        congress_id = loader.upsert_politician(
            {
                "full_name": "Taylor Public",
                "current_office": "US Senator from CA",
                "bioguide_id": "B000321",
                "external_ids": {"wikidata": "Q321"},
                "aliases": [],
                "source_system_key": "congress-legislators",
                "source_record_key": "B000321",
                "source_term_key": "sen:2025-01-03",
            }
        )
        executive_id = loader.upsert_politician(
            {
                "full_name": "Taylor Public",
                "current_office": "Vice President of the United States",
                "external_ids": {"wikidata": "Q321", "bioguide": "B000321"},
                "aliases": [],
                "source_system_key": "congress-legislators",
                "source_record_key": "executive:Q321",
                "source_term_key": "viceprez:2029-01-20",
            }
        )

        self.assertEqual("pol-congress", congress_id)
        self.assertEqual("pol-executive", executive_id)
        self.assertEqual("person-shared", loader.person_id_by_politician_id[congress_id])
        self.assertEqual("person-shared", loader.person_id_by_politician_id[executive_id])
        rpc_args = [item["args"] for item in self.fake_client.operations]
        self.assertEqual(
            ["B000321", "executive:Q321"],
            [args["p_source_record_key"] for args in rpc_args],
        )
        self.assertEqual(
            ["sen:2025-01-03", "viceprez:2029-01-20"],
            [args["p_office_term"]["source_term_key"] for args in rpc_args],
        )
        self.assertNotIn("bioguide_id", rpc_args[1]["p_profile"])
        self.assertIn(
            {
                "source_system_key": "bioguide",
                "external_id_type": "bioguide_id",
                "external_id": "B000321",
            },
            rpc_args[1]["p_trusted_external_ids"],
        )

    def test_source_profile_conflict_is_blocked_before_rpc_or_hub_write(self):
        self.use_conflicting_identity_snapshot()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        with self.assertRaises(self.loader_module.IdentityResolutionConflict):
            loader.upsert_politician(
                {
                    "full_name": "Jane Conflict",
                    "current_office": "US Representative",
                    "bioguide_id": "B000001",
                    "external_ids": {"fec": "H0CA00001"},
                    "aliases": [],
                    "source_system_key": "congress-legislators",
                    "source_record_key": "B000001",
                }
            )

        self.assertFalse(
            any(
                item.get("table") == "politicians" or item.get("type") == "rpc"
                for item in self.fake_client.operations
            )
        )
        candidates = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(candidates))
        self.assertEqual("pol-1", candidates[0]["source_legacy_politician_id"])
        self.assertEqual(
            "B000001", candidates[0]["evidence"]["source_record_key"]
        )

    def test_unanchored_source_conflict_still_creates_one_deduplicated_review_candidate(self):
        self.use_conflicting_identity_snapshot()
        self.fake_client.table_data["politicians"] = []
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())
        packet = {
            "full_name": "Future Cross-Level Person",
            "current_office": "US Representative",
            "bioguide_id": "B000001",
            "external_ids": {"fec": "H0CA00001"},
            "aliases": [],
            "source_system_key": "congress-legislators",
            "source_record_key": "future-cross-level",
        }

        for _ in range(2):
            with self.assertRaises(self.loader_module.IdentityResolutionConflict):
                loader.upsert_politician(packet)

        candidates = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(candidates))
        self.assertIsNone(candidates[0]["source_legacy_politician_id"])
        self.assertEqual(
            "future-cross-level", candidates[0]["evidence"]["source_record_key"]
        )

    def test_name_only_match_is_blocked_before_legacy_hub_update(self):
        self.fake_client.table_data["person_external_ids"] = []
        self.fake_client.table_data["legacy_profile_redirects"] = []
        self.fake_client.table_data["politicians"].append(
            {"id": "pol-name", "full_name": "Same Name", "external_ids": {}}
        )
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        with self.assertRaises(self.loader_module.IdentityResolutionConflict):
            loader.upsert_politician(
                {
                    "full_name": "Same Name",
                    "current_office": "Unknown Office",
                    "external_ids": {},
                    "aliases": [],
                }
            )

        self.assertFalse(
            any(
                item.get("type") == "update" and item.get("table") == "politicians"
                for item in self.fake_client.operations
            )
        )

    def test_observer_ignores_untrusted_ids_and_inactive_people(self):
        self.fake_client.table_data["people"] = [
            {"id": "person-untrusted", "status": "active"},
            {"id": "person-inactive", "status": "merged"},
        ]
        self.fake_client.table_data["person_external_ids"] = [
            {
                "person_id": "person-untrusted",
                "source_system_key": "bioguide",
                "external_id_type": "bioguide_id",
                "external_id": "B000777",
                "is_trusted": False,
            },
            {
                "person_id": "person-inactive",
                "source_system_key": "bioguide",
                "external_id_type": "bioguide_id",
                "external_id": "B000777",
                "is_trusted": True,
            },
        ]
        self.fake_client.table_data["legacy_profile_redirects"] = []
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        resolution = loader.observe_politician_identity(
            "pol-new",
            {
                "full_name": "Fresh Identity",
                "bioguide_id": "B000777",
                "external_ids": {},
            },
        )

        self.assertEqual("create_person", resolution.action)

    def test_complete_snapshot_retires_absent_source_record_without_deleting_identity(self):
        self.fake_client.table_data["source_records"] = [
            {
                "id": "source-seen",
                "source_system_key": "openstates",
                "source_record_key": "ocd-person/seen",
                "record_type": "person_profile",
                "record_status": "active",
                "person_id": "person-1",
            },
            {
                "id": "source-absent",
                "source_system_key": "openstates",
                "source_record_key": "ocd-person/absent",
                "record_type": "person_profile",
                "record_status": "active",
                "person_id": "person-2",
            },
        ]
        self.fake_client.table_data["person_office_terms"] = [
            {
                "id": "term-absent",
                "source_record_id": "source-absent",
                "term_status": "current",
                "person_id": "person-2",
            }
        ]
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        retired = loader.reconcile_source_snapshot(
            "openstates", {"ocd-person/seen"}
        )

        self.assertEqual(1, retired)
        source_rows = self.fake_client.table_data["source_records"]
        self.assertEqual("active", source_rows[0]["record_status"])
        self.assertEqual("retired", source_rows[1]["record_status"])
        self.assertEqual(
            "historical",
            self.fake_client.table_data["person_office_terms"][0]["term_status"],
        )
        self.assertEqual("person-2", source_rows[1]["person_id"])
        self.assertEqual(
            ["retire_source_profile_record"],
            [item["name"] for item in self.fake_client.operations],
        )

    def test_scotus_prefix_reconciliation_cannot_retire_other_legacy_records(self):
        self.fake_client.table_data["source_records"] = [
            {
                "id": "source-scotus",
                "source_system_key": "avanguardia-legacy-profile",
                "source_record_key": "scotus-seed:QOLD",
                "record_type": "person_profile",
                "record_status": "active",
            },
            {
                "id": "source-unrelated",
                "source_system_key": "avanguardia-legacy-profile",
                "source_record_key": "other-local-record",
                "record_type": "person_profile",
                "record_status": "active",
            },
        ]
        self.fake_client.table_data["person_office_terms"] = []
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        retired = loader.reconcile_source_snapshot(
            "avanguardia-legacy-profile",
            set(),
            record_key_prefix="scotus-seed:",
        )

        self.assertEqual(1, retired)
        self.assertEqual(
            ["retired", "active"],
            [row["record_status"] for row in self.fake_client.table_data["source_records"]],
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

    def test_upsert_first_seen_row_counts_prewrite_create_intent(self):
        self.fake_client.table_data["person_external_ids"] = []
        self.fake_client.table_data["legacy_profile_redirects"] = []
        self.fake_client.table_data["politicians"] = []
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        politician_id = loader.upsert_politician(
            {
                "full_name": "New Person",
                "current_office": "US Representative",
                "bioguide_id": "B000999",
                "external_ids": {},
                "aliases": [],
            }
        )

        self.assertEqual("pol-new", politician_id)
        self.assertEqual(1, summary.counts["hub_rows_inserted"])
        self.assertEqual(1, summary.counts["identity_observer_packets_checked"])
        self.assertEqual(1, summary.counts["identity_observer_create_person"])

    def test_observer_records_blocked_conflict_as_review_candidate(self):
        self.use_conflicting_identity_snapshot()
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        resolution = self.observe_conflicting_identity(loader)

        self.assertEqual("blocked_conflict", resolution.action)
        self.assertEqual(
            "deterministic_keys_match_multiple_people",
            resolution.blocked_reason,
        )
        self.assertEqual(("person-1", "person-2"), resolution.matching_person_ids)
        rows = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(rows))
        self.assertEqual(
            "identity_observer_blocked_deterministic_keys_match_multiple_people",
            rows[0]["candidate_type"],
        )
        self.assertEqual("pending", rows[0]["status"])
        self.assertEqual("pol-conflict", rows[0]["source_legacy_politician_id"])
        self.assertEqual("pol-conflict", rows[0]["candidate_legacy_politician_id"])
        self.assertIsNone(rows[0]["source_person_id"])
        self.assertIsNone(rows[0]["candidate_person_id"])
        evidence = rows[0]["evidence"]
        self.assertEqual("Jane Conflict", evidence["full_name"])
        self.assertEqual(["person-1", "person-2"], evidence["matching_person_ids"])
        self.assertEqual(
            [
                {
                    "source_system_key": "bioguide",
                    "external_id_type": "bioguide_id",
                    "external_id": "B000001",
                },
                {
                    "source_system_key": "fec",
                    "external_id_type": "fec_candidate_id",
                    "external_id": "H0CA00001",
                },
            ],
            evidence["deterministic_keys"],
        )
        self.assertEqual(1, summary.counts["identity_observer_candidates_inserted"])
        self.assertEqual(1, summary.counts["identity_observer_candidates_recorded"])

    def test_observer_updates_existing_blocked_conflict_candidate(self):
        self.use_conflicting_identity_snapshot()
        self.fake_client.table_data["identity_resolution_candidates"] = [
            {
                "id": "candidate-existing",
                "candidate_type": (
                    "identity_observer_blocked_deterministic_keys_match_multiple_people"
                ),
                "source_legacy_politician_id": "pol-conflict",
                "status": "pending",
                "evidence": {"old": True},
            }
        ]
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        self.observe_conflicting_identity(loader)

        rows = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(rows))
        self.assertEqual("candidate-existing", rows[0]["id"])
        self.assertEqual("pending", rows[0]["status"])
        self.assertEqual("pol-conflict", rows[0]["candidate_legacy_politician_id"])
        self.assertEqual("Jane Conflict", rows[0]["evidence"]["full_name"])
        self.assertNotIn("old", rows[0]["evidence"])
        candidate_operations = [
            item["type"]
            for item in self.fake_client.operations
            if item.get("table") == "identity_resolution_candidates"
        ]
        self.assertEqual(["update"], candidate_operations)
        self.assertEqual(1, summary.counts["identity_observer_candidates_updated"])
        self.assertEqual(1, summary.counts["identity_observer_candidates_recorded"])

    def test_observer_preserves_maintainer_blocked_candidate_status(self):
        self.use_conflicting_identity_snapshot()
        self.fake_client.table_data["identity_resolution_candidates"] = [
            {
                "id": "candidate-reviewed",
                "candidate_type": (
                    "identity_observer_blocked_deterministic_keys_match_multiple_people"
                ),
                "source_legacy_politician_id": "pol-conflict",
                "status": "blocked",
                "evidence": {"reviewed": True},
            }
        ]
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        self.observe_conflicting_identity(loader)

        rows = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(rows))
        self.assertEqual("blocked", rows[0]["status"])
        self.assertEqual({"reviewed": True}, rows[0]["evidence"])
        candidate_operations = [
            item["type"]
            for item in self.fake_client.operations
            if item.get("table") == "identity_resolution_candidates"
        ]
        self.assertEqual([], candidate_operations)
        self.assertEqual(1, summary.counts["identity_observer_candidates_skipped_reviewed"])

    def test_observer_records_missing_deterministic_key_as_pending_candidate(self):
        self.fake_client.table_data["person_external_ids"] = []
        self.fake_client.table_data["legacy_profile_redirects"] = []
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)

        resolution = loader.observe_politician_identity(
            "pol-pending",
            {
                "full_name": "Name Only",
                "external_ids": {"twitter": "not-deterministic"},
            },
        )

        self.assertEqual("pending_review", resolution.action)
        rows = self.fake_client.table_data["identity_resolution_candidates"]
        self.assertEqual(1, len(rows))
        self.assertEqual(
            "identity_observer_pending_missing_deterministic_identity",
            rows[0]["candidate_type"],
        )
        self.assertEqual("pending", rows[0]["status"])
        self.assertEqual("pol-pending", rows[0]["candidate_legacy_politician_id"])
        evidence = rows[0]["evidence"]
        self.assertEqual(
            "missing_deterministic_identity",
            evidence["pending_candidate"]["candidate_type"],
        )
        self.assertEqual(
            ["name only"],
            evidence["pending_candidate"]["evidence"]["normalized_names"],
        )
        self.assertEqual(1, summary.counts["identity_observer_candidates_inserted"])


if __name__ == "__main__":
    unittest.main()
