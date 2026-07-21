import unittest
from pathlib import Path


class HouseRollCallSourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.sql = (
            repository_root
            / "migrations"
            / "0025_house_roll_call_source_review.sql"
        ).read_text(encoding="utf-8")
        cls.policy = (
            repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")

    def test_approves_only_the_existing_shadow_source_and_endpoint(self):
        self.assertIn("'house-clerk-roll-call-xml'", self.sql)
        self.assertIn("'evs-roll-call-feed'", self.sql)
        self.assertIn("public.review_source_catalog_source", self.sql)
        self.assertIn("public.review_source_catalog_endpoint", self.sql)
        self.assertIn("p_new_status => 'approved'", self.sql)
        self.assertIn("p_repo_fit => 'wired'", self.sql)
        self.assertIn("v_source_status IS DISTINCT FROM 'candidate'", self.sql)
        self.assertIn("v_source_repo_fit IS DISTINCT FROM 'needs_review'", self.sql)
        self.assertIn("v_endpoint_status IS DISTINCT FROM 'candidate'", self.sql)

    def test_records_the_reviewed_shadow_evidence(self):
        for run_id in (
            "29673051187",
            "29716133242",
            "29717007354",
            "29800415718",
            "29868730671",
        ):
            self.assertIn(f"'{run_id}'", self.sql)
        self.assertIn("'shadow_member_vote_observations', 53996", self.sql)
        self.assertIn("'shadow_exact_bioguide_matches', 53996", self.sql)
        self.assertIn("'shadow_unmatched_bioguide_ids', 0", self.sql)
        self.assertIn("'shadow_govtrack_vote_cast_mismatches', 0", self.sql)
        self.assertIn("'join_policy', 'exact_xml_name_id_to_bioguide_only'", self.sql)

    def test_keeps_production_writes_disabled_and_records_the_source_contract(self):
        self.assertIn("'production_writes_enabled', false", self.sql)
        self.assertIn(
            "'production_write_status', 'disabled_pending_separate_ingestion_review'",
            self.sql,
        )
        self.assertIn("'raw_xml', 'not_retained'", self.sql)
        self.assertIn("'payload_hash', 'retain'", self.sql)
        self.assertIn("'source_url_required', true", self.sql)
        self.assertIn("'disable_path'", self.sql)
        self.assertIn("'scraper_preflight_required', false", self.sql)

    def test_links_the_catalog_source_and_records_a_forward_only_marker(self):
        self.assertIn("public.source_catalog_source_system_links", self.sql)
        self.assertIn("'house-clerk'", self.sql)
        self.assertIn("'same_source'", self.sql)
        self.assertIn("ON CONFLICT (source_slug, source_system_key, link_type)", self.sql)
        self.assertIn("'0025_house_roll_call_source_review'", self.sql)
        self.assertIn("'0025_house_roll_call_source_review',\n        25,", self.sql)
        self.assertIn("BEGIN;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_public_policy_matches_the_database_decision(self):
        self.assertIn("House Clerk roll-call XML (approved; writes disabled)", self.policy)
        self.assertIn("53,996", self.policy)
        self.assertIn("zero unmatched Bioguide IDs", self.policy)
        self.assertIn("does **not** enable production vote writes", self.policy)
        self.assertIn("Raw XML is not retained", self.policy)
        self.assertIn("Office of the Clerk, U.S. House of Representatives", self.policy)


if __name__ == "__main__":
    unittest.main()
