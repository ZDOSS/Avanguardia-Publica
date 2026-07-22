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

    def test_execute_supabase_retries_bounded_http_gateway_statuses(self):
        for message in (
            "HTTP 502 Bad Gateway",
            "HTTP 503 Service Unavailable",
            "HTTP 504 Gateway Timeout",
        ):
            with self.subTest(message=message):
                summary = SummaryStub()
                loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
                attempts = {"count": 0}

                def operation():
                    attempts["count"] += 1
                    if attempts["count"] == 1:
                        raise Exception(message)
                    return "ok"

                self.assertEqual(
                    "ok", loader.execute_supabase(operation, "gateway retry probe")
                )
                self.assertEqual(2, attempts["count"])
                self.assertEqual(1, summary.counts["supabase_transient_retries"])

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

    def test_execute_supabase_does_not_retry_integrity_codes_containing_http_digits(self):
        for code in ("22023", "23502", "23503", "23505", "55000"):
            with self.subTest(code=code):
                summary = SummaryStub()
                loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
                attempts = {"count": 0}

                def operation():
                    attempts["count"] += 1
                    raise Exception(
                        f"{{'code': '{code}', 'message': 'deterministic database error'}} "
                        "HTTP/2"
                    )

                with self.assertRaisesRegex(Exception, code):
                    loader.execute_supabase(operation, "House identity validation")

                self.assertEqual(attempts["count"], 1)
                self.assertNotIn("supabase_transient_retries", summary.counts)

    def test_execute_supabase_retries_generic_conflict_transport_errors(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        attempts = {"count": 0}

        def operation():
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise Exception("HTTP/2 stream reset after 409 Conflict")
            return "ok"

        result = loader.execute_supabase(operation, "temporary conflict")

        self.assertEqual("ok", result)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(summary.counts["supabase_transient_retries"], 1)

    def test_execute_supabase_does_not_retry_plain_conflict_errors(self):
        summary = SummaryStub()
        loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
        attempts = {"count": 0}

        def operation():
            attempts["count"] += 1
            raise Exception("409 Conflict")

        with self.assertRaisesRegex(Exception, "409 Conflict"):
            loader.execute_supabase(operation, "deterministic plain conflict")

        self.assertEqual(attempts["count"], 1)
        self.assertNotIn("supabase_transient_retries", summary.counts)

    def test_execute_supabase_retries_structured_concurrency_codes(self):
        for code in ("40001", "40P01", "55P03"):
            with self.subTest(code=code):
                summary = SummaryStub()
                loader = self.loader_module.SupabaseLoader("url", "key", summary=summary)
                attempts = {"count": 0}

                def operation():
                    attempts["count"] += 1
                    if attempts["count"] == 1:
                        raise Exception(
                            f"{{'code': '{code}', 'message': 'retry transaction'}}"
                        )
                    return "ok"

                self.assertEqual(
                    "ok", loader.execute_supabase(operation, "concurrency retry")
                )
                self.assertEqual(2, attempts["count"])
                self.assertEqual(1, summary.counts["supabase_transient_retries"])


if __name__ == "__main__":
    unittest.main()
