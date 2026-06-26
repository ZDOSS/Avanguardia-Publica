import unittest

from schema_preflight import (
    MIGRATION_HELP,
    RPC_REQUIREMENTS,
    TABLE_REQUIREMENTS,
    NIL_UUID,
    SchemaPreflightError,
    run_schema_preflight,
)


class FakeTableQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.columns = None
        self.limit_value = None

    def select(self, columns):
        self.columns = columns
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        self.client.table_checks.append(
            (self.table_name, tuple(self.columns.split(",")), self.limit_value)
        )
        if self.table_name in self.client.failing_tables:
            raise RuntimeError(f"{self.table_name} missing")
        return type("Response", (), {"data": []})()


class FakeRpcQuery:
    def __init__(self, client, name, args):
        self.client = client
        self.name = name
        self.args = args

    def execute(self):
        self.client.rpc_checks.append((self.name, self.args))
        if self.name in self.client.failing_rpcs:
            raise RuntimeError(f"{self.name} missing")
        return type("Response", (), {"data": []})()


class FakeSupabase:
    def __init__(self, failing_tables=None, failing_rpcs=None):
        self.failing_tables = set(failing_tables or ())
        self.failing_rpcs = set(failing_rpcs or ())
        self.table_checks = []
        self.rpc_checks = []

    def table(self, name):
        return FakeTableQuery(self, name)

    def rpc(self, name, args):
        return FakeRpcQuery(self, name, args)


class SchemaPreflightTests(unittest.TestCase):
    def test_dry_run_skips_without_client(self):
        run_schema_preflight(None)

    def test_success_checks_required_tables_and_rpcs(self):
        client = FakeSupabase()

        run_schema_preflight(client)

        self.assertEqual(
            {
                "politicians",
                "contact_info",
                "campaign_donors",
                "voting_records",
                "unconfirmed_mentions",
                "relationships",
                "financial_disclosures",
            },
            {req.table for req in TABLE_REQUIREMENTS},
        )
        self.assertEqual(
            [(req.table, req.columns, 0) for req in TABLE_REQUIREMENTS],
            client.table_checks,
        )
        self.assertEqual(
            [(req.name, req.args) for req in RPC_REQUIREMENTS],
            client.rpc_checks,
        )
        self.assertTrue(all(args == {"p_id": NIL_UUID} for _, args in client.rpc_checks))

    def test_failure_reports_all_missing_requirements(self):
        client = FakeSupabase(
            failing_tables={"contact_info", "financial_disclosures"},
            failing_rpcs={"get_covoting"},
        )

        with self.assertRaises(SchemaPreflightError) as raised:
            run_schema_preflight(client)

        message = str(raised.exception)
        self.assertIn(MIGRATION_HELP, message)
        self.assertIn("contact_info columns", message)
        self.assertIn("financial_disclosures columns", message)
        self.assertIn("RPC get_covoting", message)
        self.assertEqual(3, len(raised.exception.failures))


if __name__ == "__main__":
    unittest.main()
