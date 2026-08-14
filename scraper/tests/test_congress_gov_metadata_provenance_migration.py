import re
import unittest
from pathlib import Path

from schema_preflight import REQUIRED_MIGRATION_FILE, REQUIRED_MIGRATION_KEY


class CongressGovMetadataProvenanceMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.path = (
            repository_root
            / "migrations"
            / "0035_congress_gov_metadata_provenance.sql"
        )
        cls.sql = cls.path.read_text(encoding="utf-8")
        function_start = cls.sql.index(
            "CREATE FUNCTION public.upsert_congress_gov_measure_metadata("
        )
        function_end = cls.sql.index("$function$;", function_start)
        cls.function_sql = cls.sql[function_start:function_end]

    def test_is_forward_only_after_0034_and_advances_preflight_to_0035(self):
        self.assertIn(
            "'0034_congress_gov_metadata_shadow_contract'",
            self.sql,
        )
        self.assertIn("migration_version = 34", self.sql)
        self.assertIn("'0035_congress_gov_metadata_provenance'", self.sql)
        self.assertIn(
            "'0035_congress_gov_metadata_provenance',\n        35,",
            self.sql,
        )
        self.assertEqual("0035_congress_gov_metadata_provenance", REQUIRED_MIGRATION_KEY)
        self.assertEqual(
            "0035_congress_gov_metadata_provenance.sql",
            REQUIRED_MIGRATION_FILE,
        )
        self.assertTrue(self.sql.startswith("-- 0035_"))
        self.assertIn("BEGIN;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_creates_private_normalized_facts_and_exact_link_tables(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.legislative_measures",
            self.sql,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.legislative_roll_call_measure_links",
            self.sql,
        )
        self.assertIn(
            "REFERENCES public.source_records(id) ON DELETE CASCADE",
            self.sql,
        )
        self.assertIn(
            "REFERENCES public.legislative_roll_calls(source_record_id) ON DELETE CASCADE",
            self.sql,
        )
        self.assertIn(
            "CHECK (link_basis = 'exact_official_measure_identifier')",
            self.sql,
        )
        self.assertIn(
            "canonical_measure_key =\n                measure_kind || ':'",
            self.sql,
        )
        for table in (
            "legislative_measures",
            "legislative_roll_call_measure_links",
        ):
            self.assertIn(
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
                self.sql,
            )
            self.assertIn(
                f"GRANT SELECT ON TABLE public.{table} TO service_role",
                self.sql,
            )
        self.assertNotIn("CREATE POLICY", self.sql)
        self.assertNotRegex(self.sql, r"GRANT\s+SELECT.*\b(?:anon|authenticated)\b")

    def test_writer_is_one_bounded_security_definer_rpc_for_service_role_only(self):
        self.assertIn(
            "CREATE FUNCTION public.upsert_congress_gov_measure_metadata(\n"
            "    p_measures jsonb,\n"
            "    p_roll_call_links jsonb",
            self.sql,
        )
        self.assertIn("SECURITY DEFINER", self.function_sql)
        self.assertIn("SET search_path = ''", self.function_sql)
        self.assertIn("v_measure_count > 100", self.function_sql)
        self.assertIn("v_link_count > 5000", self.function_sql)
        self.assertIn("pg_advisory_xact_lock", self.function_sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION "
            "public.upsert_congress_gov_measure_metadata(jsonb, jsonb)\n"
            "    TO service_role",
            self.sql,
        )
        self.assertNotRegex(
            self.sql,
            r"GRANT\s+EXECUTE\s+ON\s+FUNCTION\s+"
            r"public\.upsert_congress_gov_measure_metadata.*\b(?:anon|authenticated)\b",
        )

    def test_nonmutating_preflight_probe_bypasses_the_write_gate(self):
        sentinel = "p_measures = '[{\"preflight\": true}]'::jsonb"
        marker_check = (
            "migration_key = '0035_congress_gov_metadata_provenance'"
        )
        self.assertIn(sentinel, self.function_sql)
        self.assertLess(
            self.function_sql.index(sentinel),
            self.function_sql.index(marker_check),
        )
        self.assertIn(
            "RETURN QUERY SELECT 0::integer, 0::integer",
            self.function_sql,
        )

    def test_provenance_is_exact_verified_and_retains_no_raw_json(self):
        self.assertIn(
            "ADD CONSTRAINT source_records_congress_gov_measure_contract",
            self.sql,
        )
        self.assertIn(
            "Congress.gov source-record namespace must be empty",
            self.sql,
        )
        self.assertIn(
            "source_catalog_slug IS NOT DISTINCT FROM 'congress-gov-api'",
            self.sql,
        )
        self.assertIn(
            "VALIDATE CONSTRAINT source_records_congress_gov_measure_contract",
            self.sql,
        )
        self.assertIn("'congress-gov'", self.function_sql)
        self.assertIn("'legislative_measure'", self.function_sql)
        self.assertIn("'congress-gov-api'", self.function_sql)
        self.assertIn("'api-v3'", self.function_sql)
        self.assertIn("raw_payload_ref", self.function_sql)
        self.assertIn("NULL,\n            v_payload_hash", self.function_sql)
        self.assertIn("'verified',\n            'active'", self.function_sql)
        self.assertIn("'raw_json_retained', false", self.function_sql)
        self.assertIn("v_payload_hash !~ '^[0-9a-f]{64}$'", self.function_sql)
        self.assertIn(
            "v_fetched_at < v_existing_last_seen_at",
            self.function_sql,
        )
        self.assertIn(
            "WHERE EXCLUDED.last_seen_at > public.source_records.last_seen_at",
            self.function_sql,
        )
        self.assertIn(
            "OR v_fetched_at > v_existing_last_seen_at",
            self.function_sql,
        )

    def test_measure_and_roll_call_joins_are_exact_identifier_only(self):
        self.assertIn(
            "v_source_record_key IS DISTINCT FROM v_expected_key",
            self.function_sql,
        )
        self.assertIn(
            "v_source_url IS DISTINCT FROM v_expected_source_url",
            self.function_sql,
        )
        self.assertIn(
            "v_official_url IS DISTINCT FROM v_expected_official_url",
            self.function_sql,
        )
        self.assertIn("v_roll_call_source_system_key := 'house-clerk'", self.function_sql)
        self.assertIn("v_roll_call_endpoint_slug := 'evs-roll-call-feed'", self.function_sql)
        self.assertIn("v_roll_call_source_system_key := 'senate-lis'", self.function_sql)
        self.assertIn("v_roll_call_endpoint_slug := 'lis-roll-call-feed'", self.function_sql)
        self.assertIn(
            "roll_call.canonical_roll_call_key = v_link_roll_call_key",
            self.function_sql,
        )
        self.assertIn(
            "v_roll_call_congress IS DISTINCT FROM v_measure_congress",
            self.function_sql,
        )
        self.assertIn(
            "'exact_official_roll_call_measure_identifier_only'",
            self.function_sql,
        )
        self.assertIn(
            "ON CONFLICT (roll_call_source_record_id, measure_source_record_id)\n"
            "        DO NOTHING",
            self.function_sql,
        )

    def test_batch_rejects_duplicate_or_unlinked_measure_identities(self):
        self.assertIn("measure contains unsupported fields", self.function_sql)
        self.assertIn("roll-call link contains unsupported fields", self.function_sql)
        self.assertIn(
            "measures contains duplicate source_record_key values",
            self.function_sql,
        )
        self.assertIn(
            "roll_call_links contains duplicate exact links",
            self.function_sql,
        )
        self.assertIn(
            "measure facts and roll-call link measure keys differ",
            self.function_sql,
        )

    def test_approval_records_three_healthy_observations_but_keeps_runtime_closed(self):
        for run_id in (31557812365, 31663634544, 31766400670):
            self.assertIn(str(run_id), self.sql)
        self.assertIn("'successful_observations', 3", self.sql)
        self.assertIn("'detail_requests_per_observation', 18", self.sql)
        self.assertIn("'successful_detail_responses_per_observation', 18", self.sql)
        self.assertIn("'exact_roll_call_measure_links_observed', 43", self.sql)
        self.assertIn("status = 'approved'", self.sql)
        self.assertIn("repo_fit = 'wired'", self.sql)
        self.assertIn("'production_writes_enabled', true", self.sql)
        self.assertIn("'runtime_default', 'disabled'", self.sql)
        self.assertIn("'scheduled_runtime_writes_enabled', false", self.sql)
        self.assertIn("'scraper_preflight_required', true", self.sql)

    def test_slice_does_not_write_people_legacy_votes_or_public_read_surfaces(self):
        forbidden_dml = re.compile(
            r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"
            r"public\.(?:people|politicians|person_roll_call_votes|voting_records)\b",
            re.IGNORECASE,
        )
        self.assertNotRegex(self.sql, forbidden_dml)
        self.assertNotIn("CREATE OR REPLACE FUNCTION public.get_", self.sql)
        self.assertIn("'public_read_path_created', false", self.sql)


if __name__ == "__main__":
    unittest.main()
