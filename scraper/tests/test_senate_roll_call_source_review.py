import re
import unittest
from pathlib import Path

from extractors.senate_roll_calls import SenateRollCall


class SenateRollCallSourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.sql = (
            repository_root
            / "migrations"
            / "0028_senate_roll_call_source_review.sql"
        ).read_text(encoding="utf-8")
        cls.policy = (
            repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")
        cls.roadmap = (
            repository_root / "docs" / "canonical_data_and_analytics_plan.md"
        ).read_text(encoding="utf-8")

    def test_approves_only_the_existing_bounded_shadow_source_and_endpoint(self):
        self.assertIn("'senate-roll-call-xml'", self.sql)
        self.assertIn("'lis-roll-call-feed'", self.sql)
        self.assertIn("public.review_source_catalog_source", self.sql)
        self.assertIn("public.review_source_catalog_endpoint", self.sql)
        self.assertIn("p_new_status => 'approved'", self.sql)
        self.assertIn("p_repo_fit => 'wired'", self.sql)
        self.assertIn("v_source_status IS DISTINCT FROM 'candidate'", self.sql)
        self.assertIn("v_source_repo_fit IS DISTINCT FROM 'needs_review'", self.sql)
        self.assertIn("v_endpoint_status IS DISTINCT FROM 'candidate'", self.sql)

    def test_records_the_corrected_production_evidence(self):
        for run_id in ("30418108958", "30420913210"):
            self.assertIn(f"'{run_id}'", self.sql)
        self.assertIn("'corrected_shadow_runs_observed', 2", self.sql)
        self.assertIn("'corrected_shadow_roll_calls', 50", self.sql)
        self.assertIn("'corrected_shadow_member_vote_observations', 4996", self.sql)
        self.assertIn("'corrected_shadow_exact_lis_matches', 4996", self.sql)
        self.assertIn("'corrected_shadow_unmatched_lis_ids', 0", self.sql)
        self.assertIn("'corrected_shadow_missing_bioguide_crosswalks', 0", self.sql)
        self.assertIn(
            "'corrected_shadow_govtrack_vote_cast_matches', 4996",
            self.sql,
        )
        self.assertIn(
            "'corrected_shadow_govtrack_vote_cast_mismatches', 0",
            self.sql,
        )
        self.assertIn("'corrected_shadow_source_request_successes', 154", self.sql)
        self.assertIn("'corrected_shadow_source_request_failures', 0", self.sql)
        self.assertIn(
            "'join_policy', "
            "'exact_xml_lis_member_id_via_trusted_lis_to_bioguide_crosswalk'",
            self.sql,
        )

    def test_preserves_the_longer_exact_identity_observation_history(self):
        for run_id in (
            "30398945569",
            "30327173703",
            "30237220453",
            "30187599543",
            "30143118597",
            "30141173654",
            "29978439083",
        ):
            self.assertIn(f"'{run_id}'", self.sql)
        self.assertIn("'legacy_comparison_member_vote_observations', 17486", self.sql)
        self.assertIn("'legacy_comparison_exact_lis_matches', 17486", self.sql)
        self.assertIn(
            "'legacy_comparison_govtrack_vote_cast_mismatches', 0",
            self.sql,
        )

    def test_declared_source_keys_match_the_extractor_reconciliation_key(self):
        roll_call = SenateRollCall(
            congress=119,
            session=2,
            congress_year=2026,
            vote_number=432,
            vote_date="2026-07-29",
            question="On Passage",
            source_url=(
                "https://www.senate.gov/legislative/LIS/roll_call_votes/"
                "vote1192/vote_119_2_00432.xml"
            ),
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
            "lis_member_id": "S001",
        }
        self.assertEqual(
            roll_call.reconciliation_key,
            roll_call_template.group(1).format(**format_values),
        )
        self.assertEqual(
            f"{roll_call.reconciliation_key}:S001",
            member_vote_template.group(1).format(**format_values),
        )

    def test_reserves_a_fail_closed_official_source_record_namespace(self):
        self.assertIn("INSERT INTO public.source_systems", self.sql)
        self.assertIn("'senate-lis'", self.sql)
        self.assertIn("'U.S. Senate Legislative Information System'", self.sql)
        self.assertIn("'government'", self.sql)
        self.assertIn("'official'", self.sql)
        self.assertIn("ON CONFLICT (key) DO NOTHING", self.sql)
        self.assertIn(
            "v_source_system_display_name IS DISTINCT FROM "
            "'U.S. Senate Legislative Information System'",
            self.sql,
        )
        self.assertIn("v_source_system_verified IS DISTINCT FROM true", self.sql)

    def test_links_the_official_namespace_and_reviewed_identifier_source(self):
        self.assertIn("public.source_catalog_source_system_links", self.sql)
        self.assertIn("'senate-lis'", self.sql)
        self.assertIn("'same_source'", self.sql)
        self.assertIn("'congress-legislators'", self.sql)
        self.assertIn("'identifier_source'", self.sql)
        self.assertIn(
            "ON CONFLICT (source_slug, source_system_key, link_type)",
            self.sql,
        )

    def test_keeps_all_senate_writes_disabled(self):
        self.assertIn("'production_writes_enabled', false", self.sql)
        self.assertIn(
            "'production_write_status', 'disabled_pending_separate_ingestion_review'",
            self.sql,
        )
        self.assertIn("'ingestion_status', 'shadow_only'", self.sql)
        self.assertIn("'raw_xml', 'not_retained'", self.sql)
        self.assertIn("'payload_hash', 'retain'", self.sql)
        self.assertIn("'source_url_required', true", self.sql)
        self.assertIn("'disable_path'", self.sql)
        self.assertIn("'scraper_preflight_required', false", self.sql)
        self.assertNotRegex(
            self.sql,
            re.compile(
                r"INSERT\s+INTO\s+public\."
                r"(source_records|legislative_roll_calls|"
                r"person_roll_call_votes|voting_records|"
                r"person_external_ids|person_names)",
                re.IGNORECASE,
            ),
        )
        self.assertNotRegex(self.sql, re.compile(r"CREATE\s+TABLE", re.IGNORECASE))
        self.assertNotIn("upsert_senate_roll_call", self.sql)

    def test_requires_prior_history_and_records_a_forward_only_marker(self):
        self.assertIn("'0027_house_roll_call_production_enablement'", self.sql)
        self.assertIn("'0028_senate_roll_call_source_review'", self.sql)
        self.assertIn("'0028_senate_roll_call_source_review',\n        28,", self.sql)
        self.assertIn("BEGIN;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_public_docs_record_the_bounded_approval_and_next_gate(self):
        self.assertIn(
            "Senate roll-call XML (approved; database-gated, manual runtime opt-in)",
            self.policy,
        )
        self.assertIn("4,996 exact LIS matches", self.policy)
        self.assertIn("154 of 154", self.policy)
        self.assertIn("does **not** enable Senate production writes", self.policy)
        self.assertIn("Raw XML is not retained", self.policy)
        self.assertIn("United States Senate", self.policy)
        self.assertIn(
            "`0028_senate_roll_call_source_review.sql`",
            self.roadmap,
        )
        self.assertIn(
            "`0030_senate_roll_call_production_enablement.sql`",
            self.roadmap,
        )


if __name__ == "__main__":
    unittest.main()
