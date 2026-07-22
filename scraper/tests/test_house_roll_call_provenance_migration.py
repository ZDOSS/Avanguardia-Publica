import re
import unittest
from pathlib import Path

from extractors.house_roll_calls import HouseRollCall


class HouseRollCallProvenanceMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repository_root = Path(__file__).resolve().parents[2]
        cls.sql = (
            repository_root
            / "migrations"
            / "0026_house_roll_call_provenance.sql"
        ).read_text(encoding="utf-8")

    def test_adds_private_source_record_keyed_fact_tables(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.legislative_roll_calls",
            self.sql,
        )
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.person_roll_call_votes",
            self.sql,
        )
        self.assertGreaterEqual(
            self.sql.count("REFERENCES public.source_records(id) ON DELETE CASCADE"),
            2,
        )
        self.assertIn(
            "UNIQUE (roll_call_source_record_id, person_id)",
            self.sql,
        )
        self.assertIn(
            "idx_person_roll_call_votes_person_roll_call",
            self.sql,
        )

    def test_tables_are_private_and_service_role_managed(self):
        for table in ("legislative_roll_calls", "person_roll_call_votes"):
            self.assertIn(
                f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY",
                self.sql,
            )
            self.assertIn(
                f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC, anon, authenticated",
                self.sql,
            )
        self.assertNotIn(" TO anon, authenticated;", self.sql)

    def test_atomic_rpc_uses_exact_bioguide_identity_only(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_house_roll_call"
        )
        function_end = self.sql.index("END;\n$function$;", function_start)
        function_sql = self.sql[function_start:function_end]

        self.assertIn("SECURITY DEFINER", function_sql)
        self.assertIn("SET search_path = ''", function_sql)
        self.assertIn("external_id.source_system_key = 'bioguide'", function_sql)
        self.assertIn("external_id.external_id_type = 'bioguide_id'", function_sql)
        self.assertIn("v_identity_is_trusted IS DISTINCT FROM true", function_sql)
        self.assertIn("v_person_status IS DISTINCT FROM 'active'", function_sql)
        self.assertIn(
            "upper(btrim(external_id.external_id)) = v_bioguide_id",
            function_sql,
        )
        self.assertIn("v_identity_match_count <> 1", function_sql)
        self.assertIn(
            "idx_person_external_ids_bioguide_normalized",
            self.sql,
        )
        self.assertNotIn("person_names", function_sql)
        self.assertNotIn("name_text", function_sql)

    def test_stable_keys_match_the_house_extractor(self):
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
        format_match = re.search(
            r"'house:%s:%s:%s',\s+v_congress,\s+v_congress_year,\s+v_roll_call_number",
            self.sql,
        )
        self.assertIsNotNone(format_match)
        self.assertEqual("house:119:2026:240", roll_call.reconciliation_key)
        self.assertIn("v_member_key := format('%s:%s'", self.sql)

    def test_rpc_retains_provenance_without_raw_xml(self):
        self.assertIn("'house-clerk-roll-call-xml'", self.sql)
        self.assertIn("'evs-roll-call-feed'", self.sql)
        self.assertIn("'verified'", self.sql)
        self.assertIn("raw_payload_ref = NULL", self.sql)
        self.assertIn("'raw_xml_retained', false", self.sql)
        self.assertIn("payload_hash", self.sql)
        self.assertIn(
            "roll_call.source_url must be the matching official House Clerk XML URL",
            self.sql,
        )

    def test_conflicting_vote_aborts_instead_of_overwriting(self):
        conflict_check = self.sql.index(
            "existing official House vote conflicts for roll call"
        )
        vote_insert = self.sql.index(
            "INSERT INTO public.person_roll_call_votes",
            conflict_check,
        )
        self.assertLess(conflict_check, vote_insert)
        self.assertIn("preserving the last valid vote", self.sql)
        self.assertNotIn("vote_cast = EXCLUDED.vote_cast", self.sql)

    def test_complete_snapshot_retires_omitted_vote_provenance(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_house_roll_call"
        )
        function_end = self.sql.index("END;\n$function$;", function_start)
        function_sql = self.sql[function_start:function_end]
        loop_end = function_sql.index("END LOOP;")
        retirement = function_sql.index(
            "UPDATE public.source_records AS source",
            loop_end,
        )

        self.assertGreater(retirement, loop_end)
        self.assertIn("record_status = 'retired'", function_sql[retirement:])
        self.assertIn(
            "omitted_from_complete_house_roll_call_snapshot",
            function_sql[retirement:],
        )
        self.assertIn("= ANY(v_supplied_bioguide_ids)", function_sql[retirement:])
        self.assertNotIn("DELETE FROM public.person_roll_call_votes", function_sql)

    def test_write_gate_rows_are_locked_before_fact_writes(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.upsert_house_roll_call"
        )
        function_end = self.sql.index("END;\n$function$;", function_start)
        function_sql = self.sql[function_start:function_end]
        source_gate_lock = function_sql.index(
            "FROM public.source_catalog_sources AS source"
        )
        endpoint_gate_lock = function_sql.index(
            "FROM public.source_catalog_endpoints AS endpoint",
            source_gate_lock,
        )
        first_fact_write = function_sql.index("INSERT INTO public.source_records")

        self.assertIn("FOR SHARE;", function_sql[source_gate_lock:first_fact_write])
        self.assertLess(source_gate_lock, endpoint_gate_lock)
        self.assertLess(endpoint_gate_lock, first_fact_write)

    def test_migration_0026_installs_the_write_gate_disabled(self):
        self.assertIn(
            "v_gate_source_writes_enabled IS DISTINCT FROM 'true'",
            self.sql,
        )
        self.assertIn(
            "v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true'",
            self.sql,
        )
        self.assertGreaterEqual(
            self.sql.count("'production_writes_enabled', false"),
            3,
        )
        self.assertIn("'disabled_pending_runtime_wiring'", self.sql)

    def test_records_forward_only_marker_and_reloads_postgrest(self):
        self.assertIn("'0025_house_roll_call_source_review'", self.sql)
        self.assertIn("'0026_house_roll_call_provenance'", self.sql)
        self.assertIn("'0026_house_roll_call_provenance',\n    26,", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertIn("REVOKE EXECUTE ON FUNCTION", self.sql)
        self.assertIn("TO service_role;", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
