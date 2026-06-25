ZERO_UUID = "00000000-0000-0000-0000-000000000000"

REQUIRED_COLUMN_CHECKS = [
    ("politicians", "state,district,external_ids"),
    ("voting_records", "roll_call_id,jurisdiction"),
    ("relationships", "id"),
    ("financial_disclosures", "doc_id,doc_url,filing_type"),
]

REQUIRED_RPC_CHECKS = [
    "get_shared_donors",
    "get_covoting",
    "get_network_ties",
]


class SchemaPreflightError(RuntimeError):
    def __init__(self, failures: list[str]):
        self.failures = failures
        message = (
            "Supabase schema preflight failed. Apply migrations/*.sql manually in "
            "filename order in the Supabase SQL editor, then run "
            "NOTIFY pgrst, 'reload schema'; if the schema cache is stale.\n"
            + "\n".join(f"- {failure}" for failure in failures)
        )
        super().__init__(message)


def run_schema_preflight(loader) -> list[str]:
    """
    Validate the live Supabase REST/RPC surface before the long ETL run.

    The project has no migration runner, so this catches common drift up front instead
    of after thousands of source requests.
    """
    if not loader.supabase:
        print("Schema preflight skipped: Supabase client is not configured.")
        return []

    print("\n=== Schema preflight ===")
    failures = []

    for table, columns in REQUIRED_COLUMN_CHECKS:
        label = f"{table}.{columns}"
        try:
            loader.execute_supabase(
                lambda table=table, columns=columns: (
                    loader.supabase.table(table).select(columns).limit(1).execute()
                ),
                f"schema preflight {label}",
            )
            print(f"  [+] {label}")
        except Exception as exc:
            failures.append(f"{label}: {exc}")

    for rpc_name in REQUIRED_RPC_CHECKS:
        try:
            loader.execute_supabase(
                lambda rpc_name=rpc_name: (
                    loader.supabase.rpc(rpc_name, {"p_id": ZERO_UUID}).execute()
                ),
                f"schema preflight rpc {rpc_name}",
            )
            print(f"  [+] rpc {rpc_name}(uuid)")
        except Exception as exc:
            failures.append(f"rpc {rpc_name}(uuid): {exc}")

    if failures:
        raise SchemaPreflightError(failures)

    print("Schema preflight passed.")
    return []
