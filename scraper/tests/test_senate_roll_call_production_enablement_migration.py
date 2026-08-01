import hashlib
import re
import unittest
from pathlib import Path


class SenateRollCallProductionEnablementMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository_root = Path(__file__).resolve().parents[2]
        cls.migration_path = (
            cls.repository_root
            / "migrations"
            / "0030_senate_roll_call_production_enablement.sql"
        )
        cls.sql = (
            cls.migration_path.read_text(encoding="utf-8")
            if cls.migration_path.is_file()
            else ""
        )
        cls.readme = (cls.repository_root / "README.md").read_text(
            encoding="utf-8"
        )
        cls.roadmap = (
            cls.repository_root / "docs" / "canonical_data_and_analytics_plan.md"
        ).read_text(encoding="utf-8")
        cls.policy = (
            cls.repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")

        wrapper_start = cls.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_senate_roll_call("
        )
        wrapper_end = cls.sql.index("END;\n$function$;", wrapper_start)
        cls.wrapper_sql = cls.sql[wrapper_start:wrapper_end]

    def test_forward_only_single_transaction_enablement_exists(self):
        self.assertTrue(self.migration_path.is_file())
        self.assertIn(
            "'0030_senate_roll_call_production_enablement'",
            self.sql,
        )
        self.assertIn("do not replay forward-only migrations", self.sql)
        self.assertIn("one transaction", self.sql)
        self.assertNotIn("pg_stat_activity", self.sql)
        self.assertEqual(1, self.sql.count("\nCOMMIT;"))
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_preflight_locks_the_exact_disabled_gate_rows_in_order(self):
        preflight_end = self.sql.index("$migration_preflight$;")
        preflight_sql = self.sql[:preflight_end]
        source_lock = preflight_sql.index("FROM public.source_catalog_sources")
        endpoint_lock = preflight_sql.index(
            "FROM public.source_catalog_endpoints",
            source_lock,
        )

        self.assertLess(source_lock, endpoint_lock)
        self.assertIn("FOR UPDATE;", preflight_sql[source_lock:endpoint_lock])
        self.assertIn("FOR UPDATE;", preflight_sql[endpoint_lock:])
        self.assertIn("'write_contract_ready_disabled'", preflight_sql)
        self.assertIn("'disabled_pending_runtime_wiring'", preflight_sql)
        self.assertIn(
            "v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb",
            preflight_sql,
        )
        self.assertIn(
            "v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb",
            preflight_sql,
        )
        self.assertIn("'public_write_barrier'", preflight_sql)
        self.assertIn("'upsert_senate_roll_call_0029'", preflight_sql)

    def test_preflight_verifies_exact_0029_function_and_constraint_contracts(self):
        preflight_end = self.sql.index("$migration_preflight$;")
        preflight_sql = self.sql[:preflight_end]

        for digest in (
            "83ebd8b6cf695c27c1061f29d73bbe69",
            "0bf895df560fb34593a6aa67624c4509",
            "60788cc0382fbb9ee9885bce9663bd31",
        ):
            self.assertIn(digest, preflight_sql)
        self.assertIn("replace(procedure.prosrc, E'\\r\\n', E'\\n')", preflight_sql)
        self.assertIn("pg_get_userbyid(procedure.proowner)", preflight_sql)
        self.assertIn("procedure.prosecdef", preflight_sql)
        self.assertIn("procedure.provolatile = 'v'", preflight_sql)
        self.assertIn("procedure.proconfig", preflight_sql)
        self.assertIn("pg_get_function_result", preflight_sql)
        self.assertIn("aclexplode", preflight_sql)
        self.assertIn("FROM pg_depend AS dependency", preflight_sql)
        self.assertIn("pg_get_constraintdef(v_constraint_oid, true)", preflight_sql)
        self.assertIn("source_records_senate_roll_call_contract", preflight_sql)

    def test_preflight_preserves_identity_and_direct_dml_closure(self):
        preflight_end = self.sql.index("$migration_preflight$;")
        preflight_sql = self.sql[:preflight_end]

        self.assertIn("uq_person_external_ids_bioguide_normalized", preflight_sql)
        self.assertIn("upper(btrim(external_id))", preflight_sql)
        self.assertIn("case-equivalent Bioguide identity rows", preflight_sql)
        self.assertIn("has_table_privilege", preflight_sql)
        self.assertIn("has_column_privilege", preflight_sql)
        self.assertIn("information_schema.columns", preflight_sql)
        for table_name in (
            "public.source_records",
            "public.legislative_roll_calls",
            "public.person_roll_call_votes",
            "public.source_catalog_sources",
            "public.source_catalog_endpoints",
        ):
            self.assertIn(table_name, preflight_sql)
        for privilege in (
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        ):
            self.assertIn(f"'{privilege}'", preflight_sql)

    def test_activation_locks_and_requires_zero_senate_facts(self):
        fact_lock = self.sql.index("LOCK TABLE public.source_records")
        zero_precondition = self.sql.index(
            "expected zero preexisting official or legacy canonical Senate facts"
        )
        wrapper_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_senate_roll_call("
        )

        self.assertLess(fact_lock, zero_precondition)
        self.assertLess(zero_precondition, wrapper_start)
        lock_sql = self.sql[fact_lock:zero_precondition]
        for table_name in (
            "public.source_records",
            "public.legislative_roll_calls",
            "public.person_roll_call_votes",
            "public.voting_records",
        ):
            self.assertIn(table_name, lock_sql)
        self.assertIn("source_system_key = 'senate-lis'", self.sql)
        self.assertIn("source_catalog_slug = 'senate-roll-call-xml'", self.sql)
        self.assertIn("chamber = 'senate'", self.sql)
        self.assertIn("roll_call_id ~ '^senate:'", self.sql)
        self.assertNotIn("DELETE FROM public.voting_records", self.sql)
        self.assertNotIn("INSERT INTO public.voting_records", self.sql)
        self.assertNotIn("UPDATE public.voting_records", self.sql)

    def test_same_oid_wrapper_keeps_preflight_independent_and_calls_only_helper(self):
        preflight = self.wrapper_sql.index(
            "COALESCE(p_roll_call ->> 'preflight', '') = 'true'"
        )
        marker = self.wrapper_sql.index(
            "'0030_senate_roll_call_production_enablement'"
        )
        helper_call = self.wrapper_sql.index(
            "FROM public.upsert_senate_roll_call_0029("
        )
        confirmation = self.wrapper_sql.index(
            "private Senate write helper returned an incomplete confirmation"
        )

        self.assertLess(preflight, marker)
        self.assertLess(marker, helper_call)
        self.assertLess(helper_call, confirmation)
        self.assertIn("INTO STRICT", self.wrapper_sql)
        self.assertIn("no_data_found OR too_many_rows", self.wrapper_sql)
        self.assertIn(
            "jsonb_array_length(p_member_votes)",
            self.wrapper_sql,
        )
        self.assertNotIn("INSERT INTO public.", self.wrapper_sql)
        self.assertNotIn("UPDATE public.", self.wrapper_sql)
        self.assertNotIn("DELETE FROM public.", self.wrapper_sql)
        self.assertNotIn("DROP FUNCTION public.upsert_senate_roll_call", self.sql)
        self.assertNotIn("ALTER FUNCTION", self.sql)

    def test_checked_in_wrapper_body_hash_matches_the_reviewed_contract(self):
        body = re.search(
            r"CREATE OR REPLACE FUNCTION public\.upsert_senate_roll_call\(.*?"
            r"AS \$function\$(.*?)\$function\$;",
            self.sql,
            re.DOTALL,
        )
        self.assertIsNotNone(body)
        digest = hashlib.md5(
            body.group(1).replace("\r\n", "\n").encode("utf-8")
        ).hexdigest()

        self.assertEqual("272267d03db8d40d3a1303db3a664b36", digest)
        self.assertGreaterEqual(self.sql.count(digest), 2)

    def test_public_acl_and_owner_only_helper_are_revalidated(self):
        validation_start = self.sql.index("DO $wrapper_validation$")
        validation_end = self.sql.index("$wrapper_validation$;")
        validation_sql = self.sql[validation_start:validation_end]

        self.assertIn(
            "REVOKE ALL ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)",
            self.sql,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)",
            self.sql,
        )
        self.assertIn("TO service_role;", self.sql)
        self.assertGreaterEqual(validation_sql.count("aclexplode"), 2)
        self.assertIn(
            "NOT has_function_privilege(\n"
            "                'service_role',\n"
            "                procedure.oid",
            validation_sql,
        )
        self.assertIn("dependency.refobjid IN", validation_sql)
        self.assertIn(
            "jsonb_build_object('preflight', true)",
            validation_sql,
        )

    def test_gate_enablement_follows_wrapper_and_precedes_marker_atomically(self):
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
        enablement_sql = self.sql[source_update:marker_insert]

        self.assertLess(function_end, source_update)
        self.assertLess(source_update, endpoint_update)
        self.assertLess(endpoint_update, marker_insert)
        self.assertEqual(2, enablement_sql.count("'production_writes_enabled', true"))
        self.assertEqual(
            2,
            enablement_sql.count("GET DIAGNOSTICS v_updated_rows = ROW_COUNT;"),
        )
        self.assertIn("'production_enabled_monotonic'", enablement_sql)
        self.assertIn("'runtime_opt_in_required'", enablement_sql)
        self.assertIn("'replaced_by_guarded_wrapper'", enablement_sql)

    def test_marker_records_manual_only_runtime_boundary(self):
        marker_start = self.sql.index("INSERT INTO public.schema_migrations")
        marker_sql = self.sql[marker_start:]

        self.assertIn(
            "'0030_senate_roll_call_production_enablement',\n    30,",
            marker_sql,
        )
        self.assertIn("'production_writes_enabled', true", marker_sql)
        self.assertIn("'runtime_opt_in_required', true", marker_sql)
        self.assertIn("'scheduled_runtime_writes_enabled', false", marker_sql)
        self.assertIn("'manual_canary_required', true", marker_sql)
        self.assertIn("'preexisting_mutating_public_writer', false", marker_sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", marker_sql)

    def test_docs_record_reviewed_canary_before_scheduled_enablement(self):
        for document in (self.readme, self.roadmap, self.policy):
            self.assertIn(
                "0030_senate_roll_call_production_enablement.sql",
                document,
            )
            self.assertIn("manual", document.lower())
            self.assertIn("schedule", document.lower())
            self.assertIn("disabled", document.lower())
            self.assertIn("voting_records", document)
            self.assertIn("30593722846", document)
            self.assertIn("2,498", document)

        self.assertIn("No transaction-drain phase", self.readme)
        self.assertIn("No old-writer drain", self.policy)
        self.assertIn("exact non-mutating replay", self.roadmap)


if __name__ == "__main__":
    unittest.main()
