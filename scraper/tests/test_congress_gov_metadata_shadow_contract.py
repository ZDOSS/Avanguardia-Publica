import re
import unittest
from pathlib import Path


class CongressGovMetadataShadowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.sql = (
            repository_root
            / "migrations"
            / "0034_congress_gov_metadata_shadow_contract.sql"
        ).read_text(encoding="utf-8")
        cls.policy = (
            repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")
        cls.roadmap = (
            repository_root / "docs" / "canonical_data_and_analytics_plan.md"
        ).read_text(encoding="utf-8")
        cls.workflow = (
            repository_root / ".github" / "workflows" / "scraper.yml"
        ).read_text(encoding="utf-8")
        cls.example_env = (
            repository_root / "scraper" / "example.env"
        ).read_text(encoding="utf-8")
        cls.main = (repository_root / "scraper" / "main.py").read_text(
            encoding="utf-8"
        )

    def test_requires_0033_and_records_forward_only_version_34(self):
        self.assertIn(
            "'0033_official_voting_records_deduplication_repair'",
            self.sql,
        )
        self.assertIn("migration_version = 33", self.sql)
        self.assertIn("'0034_congress_gov_metadata_shadow_contract'", self.sql)
        self.assertIn(
            "'0034_congress_gov_metadata_shadow_contract',\n        34,",
            self.sql,
        )
        self.assertIn("BEGIN;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_corrects_only_the_candidate_catalog_contract(self):
        self.assertIn("WHERE slug = 'congress-gov-api'", self.sql)
        self.assertIn("endpoint_slug = 'api-v3'", self.sql)
        self.assertIn("v_source_status IS DISTINCT FROM 'candidate'", self.sql)
        self.assertIn("v_source_repo_fit IS DISTINCT FROM 'needs_review'", self.sql)
        self.assertIn("v_endpoint_status IS DISTINCT FROM 'candidate'", self.sql)
        self.assertIn("'https://api.data.gov/congress/v3/'", self.sql)
        self.assertIn("'https://api.congress.gov/v3/'", self.sql)
        self.assertIn(
            "'https://github.com/LibraryOfCongress/api.congress.gov/'",
            self.sql,
        )

    def test_reserves_and_validates_the_official_source_namespace(self):
        self.assertIn("INSERT INTO public.source_systems", self.sql)
        self.assertIn("'congress-gov'", self.sql)
        self.assertIn("'Congress.gov API'", self.sql)
        self.assertIn("'government'", self.sql)
        self.assertIn("'official'", self.sql)
        self.assertIn("v_source_system_verified IS DISTINCT FROM true", self.sql)
        self.assertIn("public.source_catalog_source_system_links", self.sql)
        self.assertIn("'same_source'", self.sql)

    def test_contract_is_exact_detail_only_and_bounded(self):
        self.assertIn("'collection_endpoints_allowed', false", self.sql)
        self.assertIn(
            "'/bill/{congress}/{billType}/{billNumber}'",
            self.sql,
        )
        self.assertIn(
            "'/amendment/{congress}/{amendmentType}/{amendmentNumber}'",
            self.sql,
        )
        self.assertIn("'maximum_distinct_detail_requests_per_run', 100", self.sql)
        self.assertIn(
            "'join_policy', 'exact_official_roll_call_measure_identifier_only'",
            self.sql,
        )
        self.assertIn("skip_procedural_amendment_numbers", self.sql)

    def test_historical_contract_kept_storage_disabled_before_0035(self):
        self.assertIn("'source_status', 'candidate'", self.sql)
        self.assertIn("'repo_fit', 'needs_review'", self.sql)
        self.assertIn("'production_observation_required', true", self.sql)
        self.assertIn("'production_writes_enabled', false", self.sql)
        self.assertIn("'scraper_preflight_required', false", self.sql)
        self.assertNotRegex(
            self.sql,
            re.compile(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION|CREATE\s+TABLE|"
                r"INSERT\s+INTO\s+public\.(?:source_records|legislative_roll_calls|"
                r"person_roll_call_votes|voting_records)",
                re.IGNORECASE,
            ),
        )

    def test_key_is_optional_and_documented_for_manual_provisioning(self):
        self.assertIn(
            "CONGRESS_GOV_API_KEY: ${{ secrets.CONGRESS_GOV_API_KEY }}",
            self.workflow,
        )
        self.assertIn(
            "CONGRESS_GOV_API_KEY=your_api_data_gov_key_here",
            self.example_env,
        )
        self.assertIn("CONGRESS_GOV_API_KEY", self.policy)
        self.assertIn("CONGRESS_GOV_API_KEY", self.roadmap)
        self.assertIn("bounded scheduled private storage", self.policy)

    def test_runtime_combines_both_official_snapshots_after_their_fetches(self):
        self.assertIn("get_roll_call_measure_metadata_shadow", self.main)
        self.assertIn(
            "for report in (senate_shadow_report, house_shadow_report)",
            self.main,
        )
        self.assertIn("upstream_roll_call_count=len(official_roll_calls)", self.main)
        self.assertIn("report is not None and report.snapshot_complete", self.main)
        self.assertLess(
            self.main.index("=== House roll-call XML shadow reconciliation ==="),
            self.main.index("=== Congress.gov bill/amendment metadata shadow ==="),
        )


if __name__ == "__main__":
    unittest.main()
