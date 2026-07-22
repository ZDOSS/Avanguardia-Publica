import importlib
import sys
import types
import unittest
from unittest.mock import patch


class _Response:
    def __init__(self, data):
        self.data = data


class _RpcQuery:
    def __init__(self, client, name, args):
        self.client = client
        self.name = name
        self.args = args

    def execute(self):
        self.client.calls.append((self.name, self.args))
        return _Response(
            [
                {
                    "roll_call_source_record_id": "roll-call-source-id",
                    "member_vote_count": len(self.args["p_member_votes"]),
                }
            ]
        )


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, args):
        return _RpcQuery(self, name, args)


class _GateOffQuery:
    def execute(self):
        raise RuntimeError("House Clerk production writes are disabled")


class _GateOffClient:
    def rpc(self, _name, _args):
        return _GateOffQuery()


class _IncompleteQuery:
    def execute(self):
        return _Response(
            [
                {
                    "roll_call_source_record_id": "roll-call-source-id",
                    "member_vote_count": 0,
                }
            ]
        )


class _IncompleteClient:
    def rpc(self, _name, _args):
        return _IncompleteQuery()


class _MultipleRowsQuery:
    def execute(self):
        return _Response(
            [
                {
                    "roll_call_source_record_id": "roll-call-source-id",
                    "member_vote_count": 2,
                },
                {
                    "roll_call_source_record_id": "unexpected-second-row",
                    "member_vote_count": 2,
                },
            ]
        )


class _MultipleRowsClient:
    def rpc(self, _name, _args):
        return _MultipleRowsQuery()


class _RetryQuery:
    def __init__(self, client, name, args):
        self.client = client
        self.name = name
        self.args = args

    def execute(self):
        self.client.calls.append((self.name, self.args))
        if len(self.client.calls) == 1:
            raise RuntimeError("503 Service Unavailable")
        return _Response(
            [
                {
                    "roll_call_source_record_id": "roll-call-source-id",
                    "member_vote_count": len(self.args["p_member_votes"]),
                }
            ]
        )


class _RetryClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, args):
        return _RetryQuery(self, name, args)


class _Summary:
    def __init__(self):
        self.counts = {}

    def increment(self, key, amount=1):
        self.counts[key] = self.counts.get(key, 0) + amount


class LoaderHouseRollCallTests(unittest.TestCase):
    def setUp(self):
        self.original_supabase = sys.modules.get("supabase")
        self.original_loader = sys.modules.get("loader")
        supabase_stub = types.ModuleType("supabase")
        supabase_stub.create_client = lambda *_args, **_kwargs: None
        supabase_stub.Client = object
        sys.modules["supabase"] = supabase_stub
        sys.modules.pop("loader", None)
        self.loader_module = importlib.import_module("loader")

        self.roll_call = {
            "source_record_key": "house:119:2026:2",
            "congress": 119,
            "session": 2,
            "congress_year": 2026,
            "roll_call_number": 2,
            "vote_date": "2026-07-14",
            "question": "On Passage",
            "vote_result": "Passed",
            "source_url": "https://clerk.house.gov/evs/2026/roll002.xml",
            "payload_hash": "a" * 64,
            "fetched_at": "2026-07-21T12:00:00+00:00",
        }
        self.member_votes = [
            {
                "source_record_key": "house:119:2026:2:A000001",
                "bioguide_id": "A000001",
                "vote_cast": "yea",
            },
            {
                "source_record_key": "house:119:2026:2:B000002",
                "bioguide_id": "B000002",
                "vote_cast": "nay",
            },
        ]

    def tearDown(self):
        if self.original_loader is None:
            sys.modules.pop("loader", None)
        else:
            sys.modules["loader"] = self.original_loader
        if self.original_supabase is None:
            sys.modules.pop("supabase", None)
        else:
            sys.modules["supabase"] = self.original_supabase

    def test_atomic_house_roll_call_rpc_counts_only_confirmed_rows(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _Client()

        result = loader.upsert_house_roll_call(self.roll_call, self.member_votes)

        self.assertEqual(
            [
                (
                    "upsert_house_roll_call",
                    {
                        "p_roll_call": self.roll_call,
                        "p_member_votes": self.member_votes,
                    },
                )
            ],
            loader.supabase.calls,
        )
        self.assertEqual("roll-call-source-id", result["roll_call_source_record_id"])
        self.assertEqual(1, summary.counts["house_roll_calls_written"])
        self.assertEqual(2, summary.counts["house_member_votes_written"])

    def test_database_gate_failure_propagates_without_write_counters(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _GateOffClient()

        with self.assertRaisesRegex(RuntimeError, "production writes are disabled"):
            loader.upsert_house_roll_call(self.roll_call, self.member_votes)

        self.assertEqual({}, summary.counts)

    def test_incomplete_rpc_confirmation_does_not_count_as_a_write(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _IncompleteClient()

        with self.assertRaisesRegex(RuntimeError, "incomplete write confirmation"):
            loader.upsert_house_roll_call(self.roll_call, self.member_votes)

        self.assertEqual({}, summary.counts)

    def test_multiple_rpc_result_rows_are_rejected_as_contract_drift(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _MultipleRowsClient()

        with self.assertRaisesRegex(RuntimeError, "exactly one result row"):
            loader.upsert_house_roll_call(self.roll_call, self.member_votes)

        self.assertEqual({}, summary.counts)

    def test_transient_failure_replays_the_same_idempotent_rpc_payload(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _RetryClient()

        with patch.object(self.loader_module.time, "sleep") as sleep:
            result = loader.upsert_house_roll_call(self.roll_call, self.member_votes)

        self.assertEqual("roll-call-source-id", result["roll_call_source_record_id"])
        self.assertEqual(2, len(loader.supabase.calls))
        self.assertEqual(loader.supabase.calls[0], loader.supabase.calls[1])
        sleep.assert_called_once_with(1)
        self.assertEqual(1, summary.counts["house_roll_calls_written"])
        self.assertEqual(2, summary.counts["house_member_votes_written"])


if __name__ == "__main__":
    unittest.main()
