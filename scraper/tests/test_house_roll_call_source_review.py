import re
import unittest
from pathlib import Path

from extractors.house_roll_calls import HouseRollCall


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

    def test_declared_source_keys_match_the_extractor_reconciliation_key(self):
        roll_call = HouseRollCall(
            congress=119,
            session=2,
            congress_year=2026,
            vote_number=240,
            vote_date="2026-07-21",
            question="On Passage",
            source_url="https://clerk.house.gov/evs/2026/roll240.xml",
            member_votes=(),
        )
        roll_call_template = re.search(
            r"'roll_call_source_record_key', '([^']+)'", self.sql
        )
        member_vote_template = re.search(
            r"'member_vote_source_record_key', '([^']+)'", self.sql
        )
        self.assertIsNotNone(roll_call_template)
        self.assertIsNotNone(member_vote_template)

        format_values = {
            "congress": roll_call.congress,
            "congress_year": roll_call.congress_year,
            "roll_call_number": roll_call.vote_number,
            "bioguide_id": "A000001",
        }
        self.assertEqual(
            roll_call.reconciliation_key,
            roll_call_template.group(1).format(**format_values),
        )
        self.assertEqual(
            f"{roll_call.reconciliation_key}:A000001",
            member_vote_template.group(1).format(**format_values),
        )

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

    def test_shared_source_system_notes_are_appended_not_replaced(self):
        self.assertIn("UPDATE public.source_systems AS source_system", self.sql)
        self.assertIn("NULLIF(btrim(source_system.notes), '')", self.sql)
        self.assertIn("SET notes = concat_ws(", self.sql)
        self.assertNotIn(
            "SET notes = 'Official House Clerk source used",
            self.sql,
        )

    def test_public_policy_preserves_the_review_decision_after_production_enablement(self):
        self.assertIn(
            "House Clerk roll-call XML (approved; database-gated, runtime opt-in)",
            self.policy,
        )
        self.assertIn("53,996", self.policy)
        self.assertIn("zero unmatched Bioguide IDs", self.policy)
        self.assertIn("does **not** enable production vote writes", self.policy)
        self.assertIn(
            "`HOUSE_ROLL_CALL_WRITE_MODE` nevertheless defaults to `disabled`",
            self.policy,
        )
        self.assertIn("Raw XML is not retained", self.policy)
        self.assertIn("Office of the Clerk, U.S. House of Representatives", self.policy)


if __name__ == "__main__":
    unittest.main()
