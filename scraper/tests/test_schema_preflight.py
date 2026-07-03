import unittest

from schema_preflight import (
    REQUIRED_COLUMN_CHECKS,
    REQUIRED_RPC_CHECKS,
    ZERO_UUID,
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
        self.client.table_checks.append((self.table_name, self.columns, self.limit_value))
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


class FakeLoader:
    def __init__(self, supabase):
        self.supabase = supabase
        self.executed_descriptions = []

    def execute_supabase(self, operation, description, retries=3):
        self.executed_descriptions.append(description)
        return operation()


class SchemaPreflightTests(unittest.TestCase):
    def test_dry_run_skips_without_client(self):
        loader = FakeLoader(None)

        self.assertEqual([], run_schema_preflight(loader))
        self.assertEqual([], loader.executed_descriptions)

    def test_success_checks_required_tables_and_rpcs(self):
        client = FakeSupabase()
        loader = FakeLoader(client)

        self.assertEqual([], run_schema_preflight(loader))

        self.assertEqual(
            {
                "politicians",
                "contact_info",
                "campaign_donors",
                "voting_records",
                "unconfirmed_mentions",
                "relationships",
                "financial_disclosures",
                "source_systems",
                "people",
                "person_external_ids",
                "person_names",
                "legacy_profile_redirects",
                "identity_resolution_candidates",
                "person_merge_events",
            },
            {table for table, _ in REQUIRED_COLUMN_CHECKS},
        )
        self.assertEqual(
            [(table, columns, 1) for table, columns in REQUIRED_COLUMN_CHECKS],
            client.table_checks,
        )
        politicians_columns = dict(REQUIRED_COLUMN_CHECKS)["politicians"]
        for column in (
            "government_level",
            "government_branch",
            "office_type",
            "jurisdiction",
        ):
            self.assertIn(column, politicians_columns)
        for table in (
            "contact_info",
            "financial_disclosures",
            "campaign_donors",
            "voting_records",
            "relationships",
            "unconfirmed_mentions",
        ):
            self.assertIn("person_id", dict(REQUIRED_COLUMN_CHECKS)[table])
        self.assertEqual(
            [(rpc_name, args) for rpc_name, args, _signature in REQUIRED_RPC_CHECKS],
            client.rpc_checks,
        )
        self.assertIn(
            "get_canonical_politician_summaries",
            {rpc_name for rpc_name, _args, _signature in REQUIRED_RPC_CHECKS},
        )
        self.assertIn(
            "get_canonical_politician_header",
            {rpc_name for rpc_name, _args, _signature in REQUIRED_RPC_CHECKS},
        )
        for rpc_name in (
            "sync_legacy_profile_identity",
            "get_canonical_person_legacy_ids",
            "get_canonical_contact_info",
            "get_canonical_financial_disclosures",
            "get_canonical_campaign_donors",
            "get_canonical_voting_records",
            "get_canonical_media_mentions",
        ):
            self.assertIn(
                rpc_name,
                {name for name, _args, _signature in REQUIRED_RPC_CHECKS},
            )
        self.assertEqual(
            len(REQUIRED_COLUMN_CHECKS) + len(REQUIRED_RPC_CHECKS),
            len(loader.executed_descriptions),
        )

    def test_failure_reports_all_missing_requirements(self):
        client = FakeSupabase(
            failing_tables={"contact_info", "financial_disclosures"},
            failing_rpcs={"get_covoting"},
        )
        loader = FakeLoader(client)

        with self.assertRaises(SchemaPreflightError) as raised:
            run_schema_preflight(loader)

        message = str(raised.exception)
        self.assertIn("Supabase schema preflight failed", message)
        self.assertIn("contact_info.", message)
        self.assertIn("financial_disclosures.", message)
        self.assertIn("rpc get_covoting(uuid)", message)
        self.assertEqual(3, len(raised.exception.failures))


if __name__ == "__main__":
    unittest.main()
