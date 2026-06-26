ZERO_UUID = "00000000-0000-0000-0000-000000000000"

REQUIRED_COLUMN_CHECKS = [
    (
        "politicians",
        "id,full_name,current_office,party,state,district,external_ids,aliases,"
        "search_vector,last_updated,bioguide_id",
    ),
    (
        "contact_info",
        "politician_id,office_address,phone_number,official_website,last_updated",
    ),
    (
        "financial_disclosures",
        "politician_id,filing_type,filing_date,doc_id,doc_url",
    ),
    (
        "campaign_donors",
        "politician_id,donor_name,amount,donation_date,pac_status,fec_transaction_id",
    ),
    (
        "voting_records",
        "politician_id,bill_name,bill_summary,vote_cast,vote_date,roll_call_id,"
        "jurisdiction",
    ),
    (
        "relationships",
        "id,politician_id,related_name,relationship_type,source_api,url,last_updated,"
        "related_politician_id",
    ),
    (
        "unconfirmed_mentions",
        "politician_id,source_api,content_summary,url,sentiment_score",
    ),
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
