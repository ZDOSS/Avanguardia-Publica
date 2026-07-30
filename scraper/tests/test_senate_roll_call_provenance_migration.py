import re
import unittest
from pathlib import Path

from extractors.senate_roll_calls import SenateRollCall


class SenateRollCallProvenanceMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.sql = (
            repository_root
            / "migrations"
            / "0029_senate_roll_call_provenance.sql"
        ).read_text(encoding="utf-8")
        cls.policy = (
            repository_root / "docs" / "source_usage_policy.md"
        ).read_text(encoding="utf-8")
        cls.roadmap = (
            repository_root / "docs" / "canonical_data_and_analytics_plan.md"
        ).read_text(encoding="utf-8")

        helper_start = cls.sql.index(
            "CREATE FUNCTION public.upsert_senate_roll_call_0029"
        )
        helper_end = cls.sql.index("END;\n$function$;", helper_start)
        cls.helper_sql = cls.sql[helper_start:helper_end]

        barrier_start = cls.sql.index(
            "CREATE FUNCTION public.upsert_senate_roll_call("
        )
        barrier_end = cls.sql.index("END;\n$barrier$;", barrier_start)
        cls.barrier_sql = cls.sql[barrier_start:barrier_end]

    def test_reuses_the_existing_private_legislative_fact_tables(self):
        self.assertNotIn("CREATE TABLE", self.sql)
        for table in (
            "public.source_records",
            "public.legislative_roll_calls",
            "public.person_roll_call_votes",
        ):
            self.assertIn(f"'{table}'", self.sql)
        self.assertIn(
            "LOCK TABLE public.source_records,\n"
            "    public.legislative_roll_calls,\n"
            "    public.person_roll_call_votes",
            self.sql,
        )
        self.assertIn(
            "Senate provenance migration expected zero preexisting official Senate facts",
            self.sql,
        )

    def test_reserves_a_null_safe_senate_source_record_namespace(self):
        baseline_start = self.sql.index("DO $zero_fact_baseline$")
        baseline_end = self.sql.index(
            "$zero_fact_baseline$;",
            baseline_start,
        )
        baseline_sql = self.sql[baseline_start:baseline_end]
        constraint_start = self.sql.index(
            "ADD CONSTRAINT source_records_senate_roll_call_contract"
        )
        constraint_end = self.sql.index(
            "VALIDATE CONSTRAINT source_records_senate_roll_call_contract"
        )
        constraint_sql = self.sql[constraint_start:constraint_end]
        self.assertIn(
            "ADD CONSTRAINT source_records_senate_roll_call_contract",
            self.sql,
        )
        self.assertIn(") IS TRUE\n    )\n    NOT VALID;", self.sql)
        self.assertIn(
            "VALIDATE CONSTRAINT source_records_senate_roll_call_contract",
            self.sql,
        )
        self.assertIn(
            r"^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*$",
            self.sql,
        )
        self.assertIn(
            r"^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*:S[0-9]{3}$",
            self.sql,
        )
        self.assertIn(
            "'omitted_from_complete_senate_roll_call_snapshot'",
            self.sql,
        )
        self.assertNotIn(
            "OR source_endpoint_slug = 'lis-roll-call-feed'",
            constraint_sql,
        )
        self.assertNotIn(
            "OR source_endpoint_slug = 'lis-roll-call-feed'",
            baseline_sql,
        )
        self.assertIn(
            "source_catalog_slug\n"
            "                IS NOT DISTINCT FROM 'senate-roll-call-xml'",
            constraint_sql,
        )

    def test_preserves_the_service_role_direct_dml_closure(self):
        for privilege in (
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        ):
            self.assertIn(
                f"'{privilege}'",
                self.sql,
            )
        self.assertIn("has_table_privilege(", self.sql)
        self.assertIn("has_column_privilege(", self.sql)
        self.assertIn("information_schema.columns", self.sql)
        self.assertNotIn(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE",
            self.sql,
        )
        self.assertNotIn(
            "GRANT INSERT ON TABLE public.source_records",
            self.sql,
        )

    def test_helper_uses_only_exact_structured_identity_provenance(self):
        self.assertIn("SECURITY DEFINER", self.helper_sql)
        self.assertIn("SET search_path = ''", self.helper_sql)
        self.assertIn(
            "external_id.source_system_key = 'bioguide'",
            self.helper_sql,
        )
        self.assertIn(
            "external_id.external_id_type = 'bioguide_id'",
            self.helper_sql,
        )
        self.assertIn(
            "crosswalk_source.source_system_key = 'congress-legislators'",
            self.helper_sql,
        )
        self.assertIn(
            "crosswalk_source.record_type = 'person_profile'",
            self.helper_sql,
        )
        self.assertIn(
            "crosswalk_source.source_catalog_slug = 'congress-legislators'",
            self.helper_sql,
        )
        self.assertIn(
            "crosswalk_source.source_endpoint_slug = 'repository'",
            self.helper_sql,
        )
        self.assertIn(
            "upper(btrim(profile.external_ids ->> 'lis'))",
            self.helper_sql,
        )
        self.assertIn("external_id.is_trusted = true", self.helper_sql)
        self.assertIn("person.status = 'active'", self.helper_sql)
        self.assertNotIn("person_names", self.helper_sql)
        self.assertNotIn("name_text", self.helper_sql)
        self.assertNotIn("full_name", self.helper_sql)

    def test_rejects_duplicate_or_unproven_member_mappings(self):
        self.assertIn(
            "uq_person_external_ids_bioguide_normalized",
            self.sql,
        )
        self.assertIn("index_state.indisunique", self.sql)
        self.assertIn("index_state.indisvalid", self.sql)
        self.assertIn(
            "case-normalized Bioguide ownership index is missing or has drifted",
            self.sql,
        )
        self.assertIn(
            "member_votes contains duplicate LIS member IDs",
            self.helper_sql,
        )
        self.assertIn(
            "member_votes contains duplicate Bioguide IDs",
            self.helper_sql,
        )
        self.assertIn(
            "every Senate LIS/Bioguide pair must resolve through one stored trusted "
            "congress-legislators profile",
            self.helper_sql,
        )
        self.assertIn(
            "crosswalk_source.record_status IN ('active', 'retired')",
            self.helper_sql,
        )

    def test_stable_keys_match_the_senate_extractor(self):
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
        format_match = re.search(
            r"'senate:%s:%s:%s',\s+v_congress,\s+"
            r"v_congress_year,\s+v_roll_call_number",
            self.helper_sql,
        )
        self.assertIsNotNone(format_match)
        self.assertEqual("senate:119:2026:432", roll_call.reconciliation_key)
        self.assertIn(
            "v_member_key := format('%s:%s', v_roll_call_key, v_lis_member_id)",
            self.helper_sql,
        )
        self.assertIn(
            "roll_call.source_url must be the matching official Senate LIS XML URL",
            self.helper_sql,
        )

    def test_helper_is_monotonic_and_exact_replays_are_non_mutating(self):
        stale_check = self.helper_sql.index(
            "v_fetched_at < v_existing_last_seen_at"
        )
        same_time_check = self.helper_sql.index(
            "v_fetched_at = v_existing_last_seen_at"
        )
        first_fact_write = self.helper_sql.index(
            "INSERT INTO public.source_records"
        )
        self.assertLess(stale_check, same_time_check)
        self.assertLess(same_time_check, first_fact_write)
        self.assertIn(
            "'observation_fingerprint_version'",
            self.helper_sql,
        )
        self.assertIn(
            "'normalized_snapshot_fingerprint_version'",
            self.helper_sql,
        )
        self.assertIn(
            "v_actual_snapshot_fingerprint\n"
            "                    IS DISTINCT FROM v_normalized_snapshot_fingerprint",
            self.helper_sql,
        )
        replay_return = self.helper_sql.index(
            "RETURN QUERY SELECT\n"
            "                v_existing_roll_call_source_record_id",
            same_time_check,
        )
        self.assertLess(replay_return, first_fact_write)

    def test_conflicting_official_vote_aborts_instead_of_overwriting(self):
        self.assertIn(
            "existing Senate member-vote source record is missing its normalized fact",
            self.helper_sql,
        )
        conflict_check = self.helper_sql.index(
            "existing official Senate vote conflicts for roll call"
        )
        vote_insert = self.helper_sql.index(
            "INSERT INTO public.person_roll_call_votes",
            conflict_check,
        )
        self.assertLess(conflict_check, vote_insert)
        self.assertIn("preserving the last valid vote", self.helper_sql)
        self.assertNotIn("vote_cast = EXCLUDED.vote_cast", self.helper_sql)

    def test_complete_snapshot_retires_omitted_vote_provenance(self):
        loop_end = self.helper_sql.index("END LOOP;")
        retirement = self.helper_sql.index(
            "UPDATE public.source_records AS source",
            loop_end,
        )
        self.assertGreater(retirement, loop_end)
        self.assertIn("record_status = 'retired'", self.helper_sql[retirement:])
        self.assertIn(
            "omitted_from_complete_senate_roll_call_snapshot",
            self.helper_sql[retirement:],
        )
        self.assertIn("= ANY(v_supplied_lis_ids)", self.helper_sql[retirement:])
        self.assertNotIn(
            "DELETE FROM public.person_roll_call_votes",
            self.helper_sql,
        )
        self.assertIn(
            "- 'retirement_reason'\n"
            "                - 'retired_by_payload_hash'",
            self.helper_sql,
        )

    def test_write_gates_and_event_lock_precede_fact_writes(self):
        source_gate = self.helper_sql.index(
            "FROM public.source_catalog_sources AS source"
        )
        endpoint_gate = self.helper_sql.index(
            "FROM public.source_catalog_endpoints AS endpoint",
            source_gate,
        )
        event_lock = self.helper_sql.index(
            "pg_catalog.pg_advisory_xact_lock",
            endpoint_gate,
        )
        first_fact_write = self.helper_sql.index(
            "INSERT INTO public.source_records"
        )
        self.assertIn("FOR SHARE;", self.helper_sql[source_gate:first_fact_write])
        self.assertLess(source_gate, endpoint_gate)
        self.assertLess(endpoint_gate, event_lock)
        self.assertLess(event_lock, first_fact_write)
        self.assertIn(
            "v_gate_source_writes_enabled IS DISTINCT FROM 'true'::jsonb",
            self.helper_sql,
        )
        self.assertIn(
            "v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true'::jsonb",
            self.helper_sql,
        )

    def test_public_rpc_is_a_hard_preflight_only_barrier(self):
        self.assertIn("SECURITY DEFINER", self.barrier_sql)
        self.assertIn("SET search_path = ''", self.barrier_sql)
        self.assertIn(
            "COALESCE(p_roll_call ->> 'preflight', '') = 'true'",
            self.barrier_sql,
        )
        self.assertIn(
            "writes are disabled pending a separate runtime enablement review",
            self.barrier_sql,
        )
        self.assertNotIn("upsert_senate_roll_call_0029(", self.barrier_sql)
        self.assertIn(
            "REVOKE ALL ON FUNCTION "
            "public.upsert_senate_roll_call_0029(jsonb, jsonb)",
            self.sql,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION "
            "public.upsert_senate_roll_call(jsonb, jsonb)\n"
            "    TO service_role;",
            self.sql,
        )
        self.assertIn(
            "has_function_privilege('service_role', v_private_oid, 'EXECUTE')",
            self.sql,
        )

    def test_migration_keeps_writes_false_and_advances_preflight(self):
        self.assertGreaterEqual(
            self.sql.count("'production_writes_enabled', false"),
            3,
        )
        self.assertIn("'write_contract_ready_disabled'", self.sql)
        self.assertIn("'disabled_pending_runtime_wiring'", self.sql)
        self.assertIn("'public_write_barrier', 'installed'", self.sql)
        self.assertIn("'0028_senate_roll_call_source_review'", self.sql)
        self.assertIn("'0029_senate_roll_call_provenance'", self.sql)
        self.assertIn(
            "'0029_senate_roll_call_provenance',\n    29,",
            self.sql,
        )
        self.assertIn("'scraper_preflight_required', true", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))

    def test_docs_record_the_disabled_provenance_boundary(self):
        self.assertIn(
            "`0029_senate_roll_call_provenance.sql`",
            self.policy,
        )
        self.assertIn(
            "public Senate RPC remains a hard preflight-only barrier",
            self.policy,
        )
        self.assertIn(
            "stored `congress-legislators` source record",
            self.policy,
        )
        self.assertIn(
            "`0029_senate_roll_call_provenance.sql`",
            self.roadmap,
        )
        self.assertIn(
            "production writes remain impossible",
            self.roadmap,
        )


if __name__ == "__main__":
    unittest.main()
