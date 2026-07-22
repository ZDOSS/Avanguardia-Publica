import unittest
from pathlib import Path


class HouseRollCallProductionEnablementMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository_root = Path(__file__).resolve().parents[2]
        cls.migration_path = (
            cls.repository_root
            / "migrations"
            / "0027_house_roll_call_production_enablement.sql"
        )
        cls.sql = (
            cls.migration_path.read_text(encoding="utf-8")
            if cls.migration_path.is_file()
            else ""
        )
        cls.readme = (cls.repository_root / "README.md").read_text(encoding="utf-8")
        cls.roadmap = (
            cls.repository_root / "docs" / "canonical_data_and_analytics_plan.md"
        ).read_text(encoding="utf-8")
        cls.policy = (
            cls.repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")

    def test_forward_only_production_enablement_migration_exists(self):
        self.assertTrue(
            self.migration_path.is_file(),
            "migration 0027 must harden House observations before enabling writes",
        )
        self.assertIn("quiesce all callers", self.sql)

    def test_preflight_locks_the_disabled_reviewed_gate_rows_in_order(self):
        self.assertIn("SET LOCAL statement_timeout = '30s';", self.sql)
        self.assertIn("'0026_house_roll_call_provenance'", self.sql)
        self.assertIn("'0027_house_roll_call_production_enablement'", self.sql)
        self.assertIn("do not replay forward-only migrations", self.sql)

        preflight_end = self.sql.index("$migration_preflight$;")
        preflight_sql = self.sql[:preflight_end]
        source_lock = preflight_sql.index(
            "FROM public.source_catalog_sources"
        )
        endpoint_lock = preflight_sql.index(
            "FROM public.source_catalog_endpoints",
            source_lock,
        )
        self.assertLess(source_lock, endpoint_lock)
        self.assertIn("FOR UPDATE;", preflight_sql[source_lock:endpoint_lock])
        self.assertIn("FOR UPDATE;", preflight_sql[endpoint_lock:])
        self.assertIn("'disabled_pending_runtime_wiring'", preflight_sql)
        self.assertIn(
            "v_source_writes_enabled IS DISTINCT FROM 'false'",
            preflight_sql,
        )
        self.assertIn(
            "v_endpoint_writes_enabled IS DISTINCT FROM 'false'",
            preflight_sql,
        )
        self.assertNotIn("COALESCE(v_source_writes_enabled", preflight_sql)
        self.assertNotIn("COALESCE(v_endpoint_writes_enabled", preflight_sql)
        self.assertIn("metadata -> 'production_writes_enabled'", preflight_sql)
        self.assertIn("v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb", preflight_sql)
        self.assertIn("v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb", preflight_sql)

    def test_preflight_verifies_the_exact_reviewed_helper_contract(self):
        preflight_end = self.sql.index("$migration_preflight$;")
        preflight_sql = self.sql[:preflight_end]

        self.assertIn("p.prosrc", preflight_sql)
        self.assertIn("replace(p.prosrc, E'\\r\\n', E'\\n')", preflight_sql)
        self.assertIn("dbd0d605e017550c959157926400d395", preflight_sql)
        self.assertIn("p.prosecdef", preflight_sql)
        self.assertIn(
            "v_write_rpc_security_definer IS DISTINCT FROM true",
            preflight_sql,
        )
        self.assertIn("p.provolatile", preflight_sql)
        self.assertIn("v_write_rpc_volatility IS DISTINCT FROM 'v'", preflight_sql)
        self.assertIn("p.proconfig", preflight_sql)
        self.assertIn("pg_get_userbyid(p.proowner)", preflight_sql)
        self.assertIn("pg_get_function_result(p.oid)", preflight_sql)
        self.assertIn("aclexplode", preflight_sql)
        self.assertIn("acldefault('f', p.proowner)", preflight_sql)
        self.assertIn("acl.grantee NOT IN", preflight_sql)
        self.assertIn("FROM pg_depend AS dependency", preflight_sql)
        self.assertIn("dependency.refclassid = 'pg_proc'::regclass", preflight_sql)
        self.assertIn("dependency.refobjid = v_write_rpc_oid", preflight_sql)

    def test_rpc_rejects_stale_observations_before_any_fact_mutation(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_house_roll_call"
        )
        function_end = self.sql.index("END;\n$function$;", function_start)
        function_sql = self.sql[function_start:function_end]

        advisory_lock = function_sql.index("pg_advisory_xact_lock")
        existing_record_lock = function_sql.index(
            "FROM public.source_records AS source",
            advisory_lock,
        )
        stale_guard = function_sql.index(
            "v_fetched_at < v_existing_last_seen_at",
            existing_record_lock,
        )
        first_fact_write = function_sql.index(
            "FROM public.upsert_house_roll_call_0026(",
            stale_guard,
        )

        self.assertIn("v_existing_last_seen_at timestamptz;", function_sql)
        self.assertIn("source.last_seen_at", function_sql[advisory_lock:stale_guard])
        self.assertIn("FOR UPDATE;", function_sql[existing_record_lock:stale_guard])
        self.assertLess(advisory_lock, existing_record_lock)
        self.assertLess(existing_record_lock, stale_guard)
        self.assertLess(stale_guard, first_fact_write)
        self.assertIn("stale House roll-call observation", function_sql)
        self.assertIn("USING ERRCODE = '55000'", function_sql[stale_guard:first_fact_write])

    def test_exact_observation_retry_is_a_non_mutating_idempotent_replay(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_house_roll_call"
        )
        function_end = self.sql.index("END;\n$function$;", function_start)
        function_sql = self.sql[function_start:function_end]

        equal_guard = function_sql.index(
            "v_fetched_at = v_existing_last_seen_at"
        )
        first_fact_write = function_sql.index(
            "FROM public.upsert_house_roll_call_0026(",
            equal_guard,
        )
        equal_branch = function_sql[equal_guard:first_fact_write]

        self.assertLess(equal_guard, first_fact_write)
        self.assertIn("v_existing_payload_hash", equal_branch)
        self.assertIn("conflicting House roll-call observation timestamp", equal_branch)
        self.assertIn("v_existing_active_member_count", equal_branch)
        self.assertIn("v_existing_session IS DISTINCT FROM v_session", equal_branch)
        self.assertIn("v_existing_vote_date IS DISTINCT FROM v_vote_date", equal_branch)
        self.assertIn("v_existing_question IS DISTINCT FROM v_question", equal_branch)
        self.assertIn("v_existing_vote_result IS DISTINCT FROM v_vote_result", equal_branch)
        self.assertIn("v_existing_roll_call_metadata", equal_branch)
        self.assertIn("vote.metadata ->> 'bioguide_id'", equal_branch)
        self.assertIn("member_source.metadata ->> 'ingestion_method'", equal_branch)
        self.assertIn("member_source.metadata -> 'raw_xml_retained'", equal_branch)
        self.assertIn("v_existing_metadata -> 'raw_xml_retained'", equal_branch)
        self.assertIn("jsonb_array_elements(p_member_votes)", equal_branch)
        self.assertIn("incoming_state AS", equal_branch)
        self.assertIn("actual_state AS", equal_branch)
        self.assertEqual(
            2,
            sum(line.strip() == "EXCEPT" for line in equal_branch.splitlines()),
        )
        self.assertIn("active House member-vote set", equal_branch)
        self.assertIn("RETURN QUERY SELECT", equal_branch)
        self.assertIn("RETURN;", equal_branch)

    def test_service_role_can_only_mutate_house_facts_through_the_wrapper(self):
        permission_sql = self.sql[
            self.sql.index("REVOKE EXECUTE ON FUNCTION public.upsert_house_roll_call") :
            self.sql.index("DO $enablement$")
        ]

        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE", permission_sql)
        self.assertIn("GRANT SELECT ON TABLE", permission_sql)
        for table_name in (
            "public.source_records",
            "public.legislative_roll_calls",
            "public.person_roll_call_votes",
            "public.source_catalog_sources",
            "public.source_catalog_endpoints",
        ):
            self.assertIn(table_name, permission_sql)
        self.assertIn("FROM service_role;", permission_sql)
        self.assertIn("has_table_privilege", permission_sql)
        self.assertIn("has_column_privilege", permission_sql)
        for privilege in ("TRUNCATE", "REFERENCES", "TRIGGER"):
            self.assertIn(f"'{privilege}'", permission_sql)
        self.assertIn("has_function_privilege", permission_sql)
        self.assertGreaterEqual(permission_sql.count("aclexplode"), 2)
        self.assertIn("service_role House RPC privilege closure failed", permission_sql)

    def test_house_source_record_shape_blocks_unrelated_rpc_writers(self):
        self.assertIn(
            "ADD CONSTRAINT source_records_house_roll_call_contract",
            self.sql,
        )
        self.assertIn(
            "VALIDATE CONSTRAINT source_records_house_roll_call_contract",
            self.sql,
        )
        self.assertIn("metadata ? 'last_profile_name'", self.sql)
        self.assertIn("metadata ? 'retirement_rpc_at'", self.sql)
        self.assertIn("'omitted_from_complete_house_roll_call_snapshot'", self.sql)
        self.assertIn(
            "^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*",
            self.sql,
        )
        self.assertIn(
            "^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$",
            self.sql,
        )
        self.assertIn(
            ") IS TRUE\n    )\n    NOT VALID;",
            self.sql,
        )

    def test_case_normalized_bioguide_ownership_is_unique_before_wrapper_install(self):
        duplicate_preflight = self.sql.index(
            "case-equivalent Bioguide identity rows must be resolved before migration 0027"
        )
        unique_index = self.sql.index(
            "CREATE UNIQUE INDEX uq_person_external_ids_bioguide_normalized"
        )
        wrapper_install = self.sql.index(
            "ALTER FUNCTION public.upsert_house_roll_call(jsonb, jsonb)"
        )

        self.assertLess(duplicate_preflight, unique_index)
        self.assertLess(unique_index, wrapper_install)
        self.assertIn("upper(btrim(external_id))", self.sql)
        self.assertIn("source_system_key = 'bioguide'", self.sql)
        self.assertIn("external_id_type = 'bioguide_id'", self.sql)

    def test_gate_enablement_follows_the_hardened_rpc_in_the_same_transaction(self):
        function_end = self.sql.index("END;\n$function$;")
        source_update = self.sql.index(
            "UPDATE public.source_catalog_sources",
            function_end,
        )
        endpoint_update = self.sql.index(
            "UPDATE public.source_catalog_endpoints",
            source_update,
        )
        marker_insert = self.sql.index(
            "INSERT INTO public.schema_migrations",
            endpoint_update,
        )

        self.assertLess(function_end, source_update)
        self.assertLess(source_update, endpoint_update)
        self.assertLess(endpoint_update, marker_insert)
        enablement_sql = self.sql[source_update:marker_insert]
        self.assertEqual(2, enablement_sql.count("'production_writes_enabled', true"))
        self.assertEqual(2, enablement_sql.count("GET DIAGNOSTICS v_updated_rows = ROW_COUNT;"))
        self.assertEqual(2, enablement_sql.count("IF v_updated_rows <> 1 THEN"))
        self.assertIn("'production_enabled_monotonic'", enablement_sql)
        self.assertIn("'runtime_opt_in_required'", enablement_sql)

    def test_records_marker_preserves_private_rpc_and_avoids_legacy_or_senate_writes(self):
        marker_start = self.sql.index("INSERT INTO public.schema_migrations (")
        marker_sql = self.sql[marker_start:]
        self.assertIn(
            "'0027_house_roll_call_production_enablement',\n    27,",
            self.sql,
        )
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertIn(
            "ALTER FUNCTION public.upsert_house_roll_call(jsonb, jsonb)\n"
            "    RENAME TO upsert_house_roll_call_0026;",
            self.sql,
        )
        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.upsert_house_roll_call_0026(jsonb, jsonb)",
            self.sql,
        )
        self.assertIn("REVOKE EXECUTE ON FUNCTION", self.sql)
        self.assertIn("TO service_role;", self.sql)
        self.assertIn("'case_normalized_bioguide_unique', true", marker_sql)
        self.assertIn("'monotonic_observations', true", marker_sql)
        self.assertIn("'exact_replay_state_comparison', true", marker_sql)
        self.assertIn("'exact_replay_controlled_metadata', true", marker_sql)
        self.assertIn("'house_roll_call_source_record_contract', true", marker_sql)
        self.assertIn("'service_role_direct_dml_revoked'", marker_sql)
        self.assertIn("'strict_json_boolean_gates', true", marker_sql)
        self.assertNotIn("INSERT INTO public.voting_records", self.sql)
        self.assertNotIn("UPDATE public.voting_records", self.sql)
        self.assertNotIn("senate", self.sql.lower())
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_tracked_policy_matches_database_enabled_runtime_opt_in_rollout(self):
        for document in (self.readme, self.roadmap, self.policy):
            self.assertIn(
                "0027_house_roll_call_production_enablement.sql",
                document,
            )
            self.assertIn("runtime", document.lower())
            self.assertIn("disabled", document.lower())

        self.assertIn("database-gated, runtime opt-in", self.policy)
        self.assertIn("reviewed database gate rows", self.policy)
        self.assertIn("agree in both directions", self.policy)
        self.assertIn("table/column access to read-only", self.policy)
        self.assertIn("bounded production ETL", self.roadmap)
        self.assertIn("table/column access to read-only", self.roadmap)
        self.assertIn("quiesce", self.readme)
        self.assertIn("quiesce", self.roadmap)


if __name__ == "__main__":
    unittest.main()
