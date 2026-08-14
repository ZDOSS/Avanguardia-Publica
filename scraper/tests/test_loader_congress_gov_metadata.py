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
                    "measure_count": len(self.args["p_measures"]),
                    "roll_call_link_count": len(self.args["p_roll_call_links"]),
                }
            ]
        )


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, args):
        return _RpcQuery(self, name, args)


class _StaticQuery:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _Response(self.data)


class _StaticClient:
    def __init__(self, data):
        self.data = data

    def rpc(self, _name, _args):
        return _StaticQuery(self.data)


class _RetryQuery(_RpcQuery):
    def execute(self):
        self.client.calls.append((self.name, self.args))
        if len(self.client.calls) == 1:
            raise RuntimeError("503 Service Unavailable")
        return _Response(
            [
                {
                    "measure_count": len(self.args["p_measures"]),
                    "roll_call_link_count": len(self.args["p_roll_call_links"]),
                }
            ]
        )


class _RetryClient(_Client):
    def rpc(self, name, args):
        return _RetryQuery(self, name, args)


class _Summary:
    def __init__(self):
        self.counts = {}

    def increment(self, key, amount=1):
        self.counts[key] = self.counts.get(key, 0) + amount


class LoaderCongressGovMetadataTests(unittest.TestCase):
    def setUp(self):
        self.original_supabase = sys.modules.get("supabase")
        self.original_loader = sys.modules.get("loader")
        supabase_stub = types.ModuleType("supabase")
        supabase_stub.create_client = lambda *_args, **_kwargs: None
        supabase_stub.Client = object
        sys.modules["supabase"] = supabase_stub
        sys.modules.pop("loader", None)
        self.loader_module = importlib.import_module("loader")

        self.measures = [
            {
                "source_record_key": "bill:119:hr:8884",
                "kind": "bill",
                "congress": 119,
                "measure_type": "hr",
                "number": 8884,
                "source_url": "https://api.congress.gov/v3/bill/119/hr/8884",
                "payload_hash": "a" * 64,
                "fetched_at": "2026-08-13T12:00:00+00:00",
            }
        ]
        self.links = [
            {
                "measure_source_record_key": "bill:119:hr:8884",
                "roll_call_source_record_key": "house:119:2026:283",
            }
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

    def test_atomic_rpc_counts_only_confirmed_measure_and_link_rows(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _Client()

        result = loader.upsert_congress_gov_measure_metadata(
            self.measures,
            self.links,
        )

        self.assertEqual(
            [
                (
                    "upsert_congress_gov_measure_metadata",
                    {
                        "p_measures": self.measures,
                        "p_roll_call_links": self.links,
                    },
                )
            ],
            loader.supabase.calls,
        )
        self.assertEqual(1, result["measure_count"])
        self.assertEqual(1, result["roll_call_link_count"])
        self.assertEqual(1, summary.counts["congress_gov_measures_written"])
        self.assertEqual(
            1,
            summary.counts["congress_gov_roll_call_links_written"],
        )

    def test_rejects_unconfigured_or_out_of_bounds_batches_before_rpc(self):
        loader = self.loader_module.SupabaseLoader(None, None)
        scenarios = (
            (None, self.measures, self.links, RuntimeError),
            (_Client(), [], self.links, ValueError),
            (_Client(), self.measures, [], ValueError),
            (_Client(), [{}] * 101, self.links, ValueError),
            (_Client(), self.measures, [{}] * 5001, ValueError),
        )

        for client, measures, links, error_type in scenarios:
            with self.subTest(client=client, measure_count=len(measures)):
                loader.supabase = client
                with self.assertRaises(error_type):
                    loader.upsert_congress_gov_measure_metadata(measures, links)
                if client is not None:
                    self.assertEqual([], client.calls)

    def test_incomplete_or_multiple_rpc_confirmations_do_not_increment_counts(self):
        scenarios = (
            ([{"measure_count": 0, "roll_call_link_count": 1}], "incomplete"),
            (
                [
                    {"measure_count": 1, "roll_call_link_count": 1},
                    {"measure_count": 1, "roll_call_link_count": 1},
                ],
                "exactly one",
            ),
        )
        for response, expected_error in scenarios:
            with self.subTest(expected_error=expected_error):
                summary = _Summary()
                loader = self.loader_module.SupabaseLoader(
                    None,
                    None,
                    summary=summary,
                )
                loader.supabase = _StaticClient(response)

                with self.assertRaisesRegex(RuntimeError, expected_error):
                    loader.upsert_congress_gov_measure_metadata(
                        self.measures,
                        self.links,
                    )

                self.assertEqual({}, summary.counts)

    def test_transient_failure_replays_the_same_idempotent_atomic_payload(self):
        summary = _Summary()
        loader = self.loader_module.SupabaseLoader(None, None, summary=summary)
        loader.supabase = _RetryClient()

        with patch.object(self.loader_module.time, "sleep") as sleep:
            result = loader.upsert_congress_gov_measure_metadata(
                self.measures,
                self.links,
            )

        self.assertEqual(1, result["measure_count"])
        self.assertEqual(2, len(loader.supabase.calls))
        self.assertEqual(loader.supabase.calls[0], loader.supabase.calls[1])
        sleep.assert_called_once_with(1)
        self.assertEqual(1, summary.counts["congress_gov_measures_written"])
        self.assertEqual(
            1,
            summary.counts["congress_gov_roll_call_links_written"],
        )


if __name__ == "__main__":
    unittest.main()
