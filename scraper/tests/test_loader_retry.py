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


class LoaderRetryTests(unittest.TestCase):
    def setUp(self):
        self.scraper_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.scraper_dir))

        self.created_clients = []
        supabase_stub = types.ModuleType("supabase")

        def create_client(url, key):
            client = object()
            self.created_clients.append(client)
            return client

        supabase_stub.create_client = create_client
        supabase_stub.Client = object
        sys.modules["supabase"] = supabase_stub
        sys.modules.pop("loader", None)

        self.loader_module = importlib.import_module("loader")
        self.loader_module.time.sleep = lambda _seconds: None

    def tearDown(self):
        sys.modules.pop("loader", None)
        sys.modules.pop("supabase", None)
        try:
            sys.path.remove(str(self.scraper_dir))
        except ValueError:
            pass

    def test_execute_supabase_retries_connection_terminated(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        attempts = {"count": 0}

        def operation():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise Exception("<ConnectionTerminated error_code:0>")
            return "ok"

        result = loader.execute_supabase(operation, "test operation")

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(summary.counts["supabase_transient_retries"], 1)
        self.assertEqual(len(self.created_clients), 2)

    def test_execute_supabase_does_not_retry_schema_errors(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        attempts = {"count": 0}

        def operation():
            attempts["count"] += 1
            raise Exception("PGRST204: missing column")

        with self.assertRaisesRegex(Exception, "PGRST204"):
            loader.execute_supabase(operation, "schema error")

        self.assertEqual(attempts["count"], 1)
        self.assertNotIn("supabase_transient_retries", summary.counts)

    def test_execute_supabase_does_not_retry_duplicate_conflicts(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        attempts = {"count": 0}

        def operation():
            attempts["count"] += 1
            raise Exception(
                "{'message': 'duplicate key value violates unique constraint', "
                "'code': '23505'} HTTP/2 409 Conflict"
            )

        with self.assertRaisesRegex(Exception, "23505"):
            loader.execute_supabase(operation, "duplicate mention")

        self.assertEqual(attempts["count"], 1)
        self.assertNotIn("supabase_transient_retries", summary.counts)


if __name__ == "__main__":
    unittest.main()
