import unittest
from pathlib import Path


class SourceCatalogContextSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0023_source_inventory_context_seed.sql"
        )
        cls.sql = migration_path.read_text(encoding="utf-8")

    def test_seeds_only_private_candidate_context_sources(self):
        for slug in ("fcc-area-api", "gsa-site-scanning-api"):
            self.assertIn(f"'{slug}'", self.sql)
        self.assertIn("'candidate'", self.sql)
        self.assertIn("'needs_review'", self.sql)
        self.assertIn("'extractors_added', false", self.sql)
        self.assertIn("'public_facts_added', false", self.sql)

    def test_records_distinct_official_endpoints_and_auth_requirements(self):
        for endpoint_slug in ("area", "block-find", "websites-v1"):
            self.assertIn(f"'{endpoint_slug}'", self.sql)
        self.assertIn("'https://geo.fcc.gov/api/census/area'", self.sql)
        self.assertIn("'https://geo.fcc.gov/api/census/block/find'", self.sql)
        self.assertIn("'https://api.gsa.gov/technology/site-scanning/v1/websites'", self.sql)
        self.assertIn("'api.data.gov'", self.sql)

    def test_preserves_existing_review_decisions_and_records_a_marker(self):
        self.assertIn("status = public.source_catalog_sources.status", self.sql)
        self.assertIn("repo_fit = public.source_catalog_sources.repo_fit", self.sql)
        self.assertIn("status = public.source_catalog_endpoints.status", self.sql)
        self.assertIn("WHERE NOT EXISTS", self.sql)
        self.assertIn("'0023_source_inventory_context_seed'", self.sql)
        self.assertIn("'0023_source_inventory_context_seed',\n    23,", self.sql)
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
