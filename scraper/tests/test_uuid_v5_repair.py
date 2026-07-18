import unittest
from pathlib import Path


class UuidV5RepairMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0023_uuid_v5_search_path_repair.sql"
        )
        cls.sql = migration_path.read_text(encoding="utf-8")

    def test_repairs_sync_function_with_the_actual_extension_schema(self):
        self.assertIn("FROM pg_catalog.pg_extension", self.sql)
        self.assertIn("WHERE extension.extname = 'uuid-ossp'", self.sql)
        self.assertIn(
            "ALTER FUNCTION public.sync_legacy_profile_identity(uuid)",
            self.sql,
        )
        self.assertIn("SET search_path = pg_catalog, %I", self.sql)
        self.assertIn("pg_catalog.has_schema_privilege", self.sql)

    def test_private_probe_exercises_uuid_v5_and_sync_configuration(self):
        self.assertIn(
            "CREATE OR REPLACE FUNCTION public.preflight_canonical_uuid_v5()",
            self.sql,
        )
        self.assertIn("uuid_generate_v5($1, $2)", self.sql)
        self.assertIn("proc.proconfig", self.sql)
        self.assertIn("v_expected_search_path", self.sql)
        self.assertIn("RETURN true;", self.sql)
        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.preflight_canonical_uuid_v5()",
            self.sql,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.preflight_canonical_uuid_v5()",
            self.sql,
        )

    def test_records_forward_only_marker_and_reloads_postgrest(self):
        self.assertIn("'0023_uuid_v5_search_path_repair'", self.sql)
        self.assertIn("'0023_uuid_v5_search_path_repair',\n    23,", self.sql)
        self.assertIn("BEGIN;", self.sql)
        self.assertIn("SET LOCAL statement_timeout = '30s';", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
