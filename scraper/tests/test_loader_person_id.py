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


class FakeQuery:
    def __init__(self, client, table_name=None, rpc_name=None, rpc_args=None):
        self.client = client
        self.table_name = table_name
        self.rpc_name = rpc_name
        self.rpc_args = rpc_args

    def upsert(self, payload, on_conflict=None):
        self.client.operations.append(
            {
                "type": "upsert",
                "table": self.table_name,
                "payload": payload,
                "on_conflict": on_conflict,
            }
        )
        return self

    def insert(self, payload):
        self.client.operations.append(
            {"type": "insert", "table": self.table_name, "payload": payload}
        )
        return self

    def select(self, _columns):
        return self

    def in_(self, _column, _values):
        return self

    def execute(self):
        if self.rpc_name == "sync_legacy_profile_identity":
            self.client.operations.append(
                {"type": "rpc", "name": self.rpc_name, "args": self.rpc_args}
            )
            return type("Response", (), {"data": [{"person_id": "person-1"}]})()
        if self.table_name in self.client.error_by_table:
            raise RuntimeError(self.client.error_by_table[self.table_name])
        return type("Response", (), {"data": []})()


class FakeSupabase:
    def __init__(self):
        self.operations = []
        self.error_by_table = {}

    def table(self, table_name):
        return FakeQuery(self, table_name=table_name)

    def rpc(self, rpc_name, args):
        return FakeQuery(self, rpc_name=rpc_name, rpc_args=args)


class LoaderPersonIdTests(unittest.TestCase):
    def setUp(self):
        self.scraper_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.scraper_dir))

        self.fake_client = FakeSupabase()
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

    def test_contact_info_stamps_cached_person_id(self):
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())
        loader.person_id_by_politician_id["pol-1"] = "person-1"

        loader.upsert_contact_info("pol-1", {"phone_number": "555-0100"})

        operation = self.fake_client.operations[-1]
        self.assertEqual("contact_info", operation["table"])
        self.assertEqual("person-1", operation["payload"]["person_id"])
        self.assertEqual("pol-1", operation["payload"]["politician_id"])

    def test_batch_spoke_write_syncs_and_stamps_person_id(self):
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())

        loader.upsert_campaign_donors(
            "pol-1",
            [
                {
                    "donor_name": "Jane Donor",
                    "amount": 25,
                    "donation_date": "2026-01-01",
                    "fec_transaction_id": "tx-1",
                }
            ],
        )

        rpc_operation = self.fake_client.operations[0]
        upsert_operation = self.fake_client.operations[-1]
        self.assertEqual("sync_legacy_profile_identity", rpc_operation["name"])
        self.assertEqual({"p_politician_id": "pol-1"}, rpc_operation["args"])
        self.assertEqual("campaign_donors", upsert_operation["table"])
        self.assertEqual("person-1", upsert_operation["payload"][0]["person_id"])
        self.assertEqual("pol-1", upsert_operation["payload"][0]["politician_id"])

    def test_news_provider_provenance_is_not_flattened_to_aggregator(self):
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())
        loader.person_id_by_politician_id["pol-1"] = "person-1"

        loader.process_mentions(
            "pol-1",
            [
                {
                    "content_summary": "Headline",
                    "url": "https://publisher.test/story",
                    "source_api": "GDELT",
                }
            ],
            "NewsAggregator",
        )

        operation = self.fake_client.operations[-1]
        self.assertEqual("unconfirmed_mentions", operation["table"])
        self.assertEqual("GDELT", operation["payload"]["source_api"])
        self.assertEqual("person-1", operation["payload"]["person_id"])

    def test_spoke_database_errors_raise_instead_of_reporting_success(self):
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())
        loader.person_id_by_politician_id["pol-1"] = "person-1"
        cases = [
            (
                "contact_info",
                lambda: loader.upsert_contact_info("pol-1", {"phone_number": "555-0100"}),
            ),
            (
                "campaign_donors",
                lambda: loader.upsert_campaign_donors(
                    "pol-1",
                    [{"donor_name": "Donor", "fec_transaction_id": "tx-1"}],
                ),
            ),
            (
                "voting_records",
                lambda: loader.upsert_voting_records(
                    "pol-1",
                    [{"bill_name": "HB 1", "vote_date": "2026-01-01"}],
                ),
            ),
            (
                "unconfirmed_mentions",
                lambda: loader.process_mentions(
                    "pol-1",
                    [{"content_summary": "Headline", "url": "https://example.test"}],
                    "Currents",
                ),
            ),
        ]
        for table_name, operation in cases:
            with self.subTest(table=table_name):
                self.fake_client.error_by_table = {
                    table_name: "permission denied; 'code': '42501'"
                }
                with self.assertRaises(RuntimeError):
                    operation()
        self.fake_client.error_by_table = {}

    def test_mention_suppresses_only_confirmed_unique_duplicate(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        loader.person_id_by_politician_id["pol-1"] = "person-1"
        self.fake_client.error_by_table = {
            "unconfirmed_mentions": (
                "duplicate key value violates unique constraint; 'code': '23505'"
            )
        }

        loader.process_mentions(
            "pol-1",
            [{"content_summary": "Headline", "url": "https://example.test"}],
            "Currents",
        )

        self.assertEqual(1, summary.counts["media_mentions_duplicates"])

    def test_relationship_name_resolution_failure_prevents_relationship_write(self):
        loader = self.loader_module.SupabaseLoader("url", "key", summary=SummaryStub())
        loader.person_id_by_politician_id["pol-1"] = "person-1"
        self.fake_client.error_by_table = {
            "politicians": "schema cache failure; 'code': 'PGRST204'"
        }

        with self.assertRaises(RuntimeError):
            loader.upsert_relationships(
                "pol-1",
                [{"related_name": "Other Person", "relationship_type": "Position"}],
            )

        self.assertFalse(
            any(item.get("table") == "relationships" for item in self.fake_client.operations)
        )


if __name__ == "__main__":
    unittest.main()
