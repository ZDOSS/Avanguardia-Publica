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

    def execute(self):
        if self.rpc_name == "sync_legacy_profile_identity":
            self.client.operations.append(
                {"type": "rpc", "name": self.rpc_name, "args": self.rpc_args}
            )
            return type("Response", (), {"data": [{"person_id": "person-1"}]})()
        return type("Response", (), {"data": []})()


class FakeSupabase:
    def __init__(self):
        self.operations = []

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


if __name__ == "__main__":
    unittest.main()
