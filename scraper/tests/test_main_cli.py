import io
import importlib
import json
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

class FakeLoader:
    def __init__(self, configured=True):
        self.supabase = object() if configured else None


def summary_json(output: str) -> dict:
    line = next(
        item for item in output.splitlines() if item.startswith("ETL_SUMMARY_JSON=")
    )
    return json.loads(line.removeprefix("ETL_SUMMARY_JSON="))


class MainCliTests(unittest.TestCase):
    def setUp(self):
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda: None
        supabase_stub = types.ModuleType("supabase")
        supabase_stub.create_client = lambda _url, _key: object()
        supabase_stub.Client = object
        sys.modules["dotenv"] = dotenv_stub
        sys.modules["supabase"] = supabase_stub
        sys.modules.pop("main", None)
        sys.modules.pop("loader", None)
        self.scraper_main = importlib.import_module("main")

    def tearDown(self):
        for module_name in ("main", "loader", "dotenv", "supabase"):
            sys.modules.pop(module_name, None)

    def test_preflight_only_stops_before_extractors_and_reports_success(self):
        loader = FakeLoader(configured=True)
        output = io.StringIO()

        with (
            patch.dict(
                os.environ,
                {"SUPABASE_URL": "https://example.invalid", "SUPABASE_KEY": "service-key"},
                clear=True,
            ),
            patch.object(self.scraper_main, "load_dotenv"),
            patch.object(self.scraper_main, "SupabaseLoader", return_value=loader),
            patch.object(self.scraper_main, "run_schema_preflight") as preflight,
            patch.object(self.scraper_main, "get_congress_members") as congress,
            redirect_stdout(output),
        ):
            self.scraper_main.main(["--preflight-only"])

        preflight.assert_called_once_with(loader)
        congress.assert_not_called()
        self.assertIn("Preflight-only validation passed", output.getvalue())
        payload = summary_json(output.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual("passed", payload["schema_preflight"]["status"])

    def test_preflight_only_requires_live_supabase_credentials(self):
        loader = FakeLoader(configured=False)
        output = io.StringIO()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.scraper_main, "load_dotenv"),
            patch.object(self.scraper_main, "SupabaseLoader", return_value=loader),
            patch.object(self.scraper_main, "run_schema_preflight") as preflight,
            patch.object(self.scraper_main, "get_congress_members") as congress,
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            self.scraper_main.main(["--preflight-only"])

        self.assertIn("no live schema was validated", str(raised.exception))
        preflight.assert_not_called()
        congress.assert_not_called()
        payload = summary_json(output.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual("failed", payload["schema_preflight"]["status"])

    def test_invalid_house_write_mode_fails_before_preflight_or_extractors(self):
        output = io.StringIO()

        with (
            patch.dict(
                os.environ,
                {"HOUSE_ROLL_CALL_WRITE_MODE": "typo"},
                clear=True,
            ),
            patch.object(self.scraper_main, "load_dotenv"),
            patch.object(self.scraper_main, "SupabaseLoader") as loader,
            patch.object(self.scraper_main, "run_schema_preflight") as preflight,
            patch.object(self.scraper_main, "get_congress_members") as congress,
            redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            self.scraper_main.main(["--preflight-only"])

        self.assertIn("HOUSE_ROLL_CALL_WRITE_MODE", str(raised.exception))
        loader.assert_not_called()
        preflight.assert_not_called()
        congress.assert_not_called()
        payload = summary_json(output.getvalue())
        self.assertFalse(payload["success"])
        self.assertEqual(1, len(payload["errors"]))
        self.assertEqual("configuration", payload["errors"][0]["scope"])

    def test_house_shadow_does_not_receive_legacy_profile_vote_map(self):
        loader = MagicMock()
        loader.supabase = object()
        loader.upsert_politician.return_value = "politician-id"
        member = {
            "full_name": "Test Representative",
            "bioguide_id": "T000001",
            "office_type": "representative",
            "current_office": "US Representative",
            "external_ids": {"govtrack": 12345},
            "contact": {},
            "source_system_key": "congress-legislators",
            "source_record_key": "bioguide:T000001",
        }
        shadow_report = MagicMock()
        shadow_report.counters.return_value = {}
        shadow_report.description.return_value = "bounded shadow"
        output = io.StringIO()

        with (
            patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.invalid",
                    "SUPABASE_KEY": "service-key",
                },
                clear=True,
            ),
            patch.object(self.scraper_main, "load_dotenv"),
            patch.object(self.scraper_main, "SupabaseLoader", return_value=loader),
            patch.object(self.scraper_main, "run_schema_preflight"),
            patch.object(self.scraper_main, "get_congress_members", return_value=[member]),
            patch.object(self.scraper_main, "get_house_disclosure_index", return_value={}),
            patch.object(
                self.scraper_main,
                "get_voting_records",
                return_value=[
                    {
                        "bill_summary": (
                            "https://www.govtrack.us/congress/votes/119-2026/h2"
                        ),
                        "vote_cast": "Yea",
                    }
                ],
            ),
            patch.object(self.scraper_main, "get_littlesis", return_value=([], [])),
            patch.object(self.scraper_main, "get_news_data", return_value=[]),
            patch.object(
                self.scraper_main,
                "get_recent_senate_roll_call_shadow",
                return_value=shadow_report,
            ),
            patch.object(
                self.scraper_main,
                "get_recent_house_roll_call_shadow",
                return_value=shadow_report,
            ) as house_shadow,
            patch.object(self.scraper_main, "write_house_roll_calls", return_value=0),
            patch.object(self.scraper_main, "get_state_politicians", return_value=[]),
            patch.object(
                self.scraper_main, "get_federal_exec_judicial", return_value=[]
            ),
            patch.object(self.scraper_main, "get_provider_status", return_value={}),
            patch.object(self.scraper_main, "run_identity_health_check"),
            patch.object(self.scraper_main, "run_source_catalog_review_check"),
            patch.object(self.scraper_main, "run_source_record_freshness_check"),
            patch.object(self.scraper_main.time, "sleep"),
            redirect_stdout(output),
        ):
            self.scraper_main.main([])

        house_shadow.assert_called_once()
        self.assertEqual(({"T000001"},), house_shadow.call_args.args)


if __name__ == "__main__":
    unittest.main()
