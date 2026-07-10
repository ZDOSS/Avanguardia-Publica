import unittest
from pathlib import Path


class SourceProfileRpcSqlContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration = Path(__file__).resolve().parents[2] / "migrations" / "0022_project_stabilization.sql"
        cls.sql = migration.read_text(encoding="utf-8")

    def test_initial_source_record_requires_trusted_identity_key(self):
        self.assertIn(
            "an initial source profile requires at least one trusted external identity key",
            self.sql,
        )

    def test_inactive_identity_owner_cannot_be_reassigned(self):
        self.assertIn("owner.status = 'inactive'", self.sql)
        self.assertIn(
            "a trusted identity key is owned by an inactive or invalid merged person",
            self.sql,
        )

    def test_provenance_and_successive_term_lifecycle_are_atomic(self):
        for parameter in (
            "p_source_catalog_slug text DEFAULT NULL",
            "p_source_endpoint_slug text DEFAULT NULL",
            "p_source_updated_at timestamptz DEFAULT NULL",
        ):
            self.assertIn(parameter, self.sql)
        self.assertIn("SET term_status = 'historical'", self.sql)

    def test_record_and_current_terms_retire_in_one_service_rpc(self):
        function_start = self.sql.index(
            "CREATE OR REPLACE FUNCTION public.retire_source_profile_record"
        )
        function_end = self.sql.index("END;\n$$;", function_start)
        function_sql = self.sql[function_start:function_end]

        term_update = function_sql.index("UPDATE public.person_office_terms")
        record_update = function_sql.index("UPDATE public.source_records", term_update)
        self.assertLess(term_update, record_update)
        self.assertIn("term_status = 'historical'", function_sql)
        self.assertIn("record_status = 'retired'", function_sql)


if __name__ == "__main__":
    unittest.main()
