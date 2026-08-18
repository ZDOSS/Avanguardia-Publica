import re
import unittest
from pathlib import Path


class CongressGovScheduledEnablementMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.path = (
            repository_root
            / "migrations"
            / "0036_congress_gov_scheduled_enablement.sql"
        )
        cls.sql = cls.path.read_text(encoding="utf-8")

    def test_is_forward_only_after_0035_and_records_its_preflight_marker(self):
        self.assertTrue(self.sql.startswith("-- 0036_"))
        self.assertIn("BEGIN;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))
        self.assertIn(
            "migration_key = '0035_congress_gov_metadata_provenance'",
            self.sql,
        )
        self.assertIn("migration_version = 35", self.sql)
        self.assertIn(
            "migration_key = '0036_congress_gov_scheduled_enablement'",
            self.sql,
        )
        self.assertIn(
            "'0036_congress_gov_scheduled_enablement',\n        36,",
            self.sql,
        )
        self.assertIn("'scraper_preflight_required', true", self.sql)

    def test_requires_the_exact_reviewed_canary_and_database_baseline(self):
        self.assertIn("'manual_canary_run_id', 31833856216", self.sql)
        self.assertIn(
            "'9d2d74e8c56fa8d7857096f312b8a72f2535440b'",
            self.sql,
        )
        self.assertIn("'schema_preflight_status', 'passed'", self.sql)
        self.assertIn("'detail_attempts', 18", self.sql)
        self.assertIn("'detail_successes', 18", self.sql)
        self.assertIn("'detail_failures', 0", self.sql)
        self.assertIn("'measure_rows_confirmed', 18", self.sql)
        self.assertIn("'exact_roll_call_measure_links_confirmed', 43", self.sql)
        self.assertIn("'linked_roll_calls_confirmed', 40", self.sql)
        self.assertIn("'write_attempts', 1", self.sql)
        self.assertIn("'write_successes', 1", self.sql)
        self.assertIn("'write_failures', 0", self.sql)
        self.assertIn("v_source_record_count <> 18", self.sql)
        self.assertIn("v_measure_count <> 18", self.sql)
        self.assertIn("v_bill_count <> 15", self.sql)
        self.assertIn("v_amendment_count <> 3", self.sql)
        self.assertIn("v_link_count <> 43", self.sql)
        self.assertIn("v_linked_roll_call_count <> 40", self.sql)

    def test_revalidates_private_exact_provenance_and_nonmutating_replay(self):
        self.assertIn("source.raw_payload_ref IS NULL", self.sql)
        self.assertIn("source.payload_hash ~ '^[0-9a-f]{64}$'", self.sql)
        self.assertIn("source.person_id IS NULL", self.sql)
        self.assertIn("source.legacy_politician_id IS NULL", self.sql)
        self.assertIn("'exact_official_measure_identifier'", self.sql)
        self.assertIn(
            "'exact_official_roll_call_measure_identifier_only'",
            self.sql,
        )
        self.assertIn("public.voting_records AS vote", self.sql)
        self.assertIn("'database_audit_violations', 0", self.sql)
        self.assertIn("'legacy_measure_key_rows', 0", self.sql)
        self.assertIn("'raw_json_retained', false", self.sql)
        self.assertIn("'exact_replay_count', 18", self.sql)
        self.assertIn("'exact_replay_link_count', 43", self.sql)
        self.assertIn("'exact_replay_row_images_changed', false", self.sql)
        self.assertIn("'exact_replay_transaction_ids_changed', false", self.sql)

    def test_preserves_private_service_role_only_storage(self):
        self.assertIn("NOT relation.relrowsecurity", self.sql)
        self.assertIn("has_table_privilege('anon'", self.sql)
        self.assertIn("'authenticated', relation.oid, 'SELECT'", self.sql)
        self.assertIn("'service_role', relation.oid, 'SELECT'", self.sql)
        self.assertIn("has_function_privilege('anon'", self.sql)
        self.assertIn("has_function_privilege('authenticated'", self.sql)
        self.assertIn("has_function_privilege('service_role'", self.sql)
        self.assertIn("FROM pg_policies", self.sql)
        self.assertIn("FROM pg_views", self.sql)
        self.assertIn("'public_read_path_created', false", self.sql)

    def test_enables_only_the_existing_bounded_scheduled_path(self):
        self.assertIn("'scheduled_runtime_writes_enabled', true", self.sql)
        self.assertIn("'runtime_default', 'disabled'", self.sql)
        self.assertIn("'manual_input_default', 'disabled'", self.sql)
        self.assertIn("'unknown_events_enabled', false", self.sql)
        self.assertIn("'maximum_distinct_detail_requests_per_run', 100", self.sql)
        self.assertIn("'maximum_roll_call_links_per_run', 5000", self.sql)
        self.assertIn(
            "'phase-4-congress-gov-scheduled-enablement'",
            self.sql,
        )
        self.assertIn("'approved',\n            'approved'", self.sql)

    def test_does_not_change_fact_writers_or_write_public_and_legacy_facts(self):
        forbidden_dml = re.compile(
            r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
            r"public\.(?:source_records|legislative_measures|"
            r"legislative_roll_call_measure_links|legislative_roll_calls|"
            r"person_roll_call_votes|voting_records|people|politicians)\b",
            re.IGNORECASE,
        )
        self.assertNotRegex(self.sql, forbidden_dml)
        self.assertNotIn("CREATE FUNCTION", self.sql)
        self.assertNotIn("CREATE OR REPLACE FUNCTION", self.sql)
        self.assertNotIn("CREATE POLICY", self.sql)
        self.assertNotIn("GRANT ", self.sql)


if __name__ == "__main__":
    unittest.main()
