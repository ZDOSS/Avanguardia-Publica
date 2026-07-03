ZERO_UUID = "00000000-0000-0000-0000-000000000000"

REQUIRED_COLUMN_CHECKS = [
    (
        "politicians",
        "id,full_name,current_office,party,state,district,external_ids,aliases,"
        "government_level,government_branch,office_type,jurisdiction,"
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
    (
        "source_systems",
        "key,display_name,source_kind,trust_level,verified,created_at,updated_at",
    ),
    (
        "people",
        "id,primary_name,display_name,status,merged_into_person_id,created_at,updated_at",
    ),
    (
        "person_external_ids",
        "person_id,source_system_key,external_id_type,external_id,is_trusted,"
        "source_legacy_politician_id",
    ),
    (
        "person_names",
        "person_id,source_system_key,legacy_politician_id,name_text,normalized_name,"
        "name_type,is_primary",
    ),
    (
        "legacy_profile_redirects",
        "legacy_politician_id,person_id,canonical_politician_id,resolution_method,"
        "confidence,created_at,updated_at",
    ),
    (
        "identity_resolution_candidates",
        "id,candidate_type,source_legacy_politician_id,candidate_legacy_politician_id,"
        "source_person_id,candidate_person_id,status,score,evidence,created_at,updated_at",
    ),
    (
        "person_merge_events",
        "id,survivor_person_id,merged_person_id,reason,evidence,created_at",
    ),
]

REQUIRED_RPC_CHECKS = [
    ("get_shared_donors", {"p_id": ZERO_UUID}, "get_shared_donors(uuid)"),
    ("get_covoting", {"p_id": ZERO_UUID}, "get_covoting(uuid)"),
    ("get_network_ties", {"p_id": ZERO_UUID}, "get_network_ties(uuid)"),
    (
        "get_canonical_politician_summaries",
        {"search_query": None, "result_limit": 1, "result_offset": 0},
        "get_canonical_politician_summaries(text, integer, integer)",
    ),
    (
        "get_canonical_politician_header",
        {"p_id": ZERO_UUID},
        "get_canonical_politician_header(uuid)",
    ),
    (
        "sync_legacy_profile_identity",
        {"p_politician_id": ZERO_UUID},
        "sync_legacy_profile_identity(uuid)",
    ),
    (
        "get_canonical_person_legacy_ids",
        {"profile_id": ZERO_UUID},
        "get_canonical_person_legacy_ids(uuid)",
    ),
    (
        "get_canonical_contact_info",
        {"p_id": ZERO_UUID},
        "get_canonical_contact_info(uuid)",
    ),
    (
        "get_canonical_financial_disclosures",
        {"p_id": ZERO_UUID, "result_limit": 1, "result_offset": 0},
        "get_canonical_financial_disclosures(uuid, integer, integer)",
    ),
    (
        "get_canonical_campaign_donors",
        {"p_id": ZERO_UUID, "result_limit": 1, "result_offset": 0},
        "get_canonical_campaign_donors(uuid, integer, integer)",
    ),
    (
        "get_canonical_voting_records",
        {
            "p_id": ZERO_UUID,
            "result_limit": 1,
            "result_offset": 0,
            "vote_cast_filter": None,
        },
        "get_canonical_voting_records(uuid, integer, integer, text)",
    ),
    (
        "get_canonical_media_mentions",
        {"p_id": ZERO_UUID, "result_limit": 1, "result_offset": 0},
        "get_canonical_media_mentions(uuid, integer, integer)",
    ),
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

    for rpc_name, args, signature in REQUIRED_RPC_CHECKS:
        try:
            loader.execute_supabase(
                lambda rpc_name=rpc_name, args=args: (
                    loader.supabase.rpc(rpc_name, args).execute()
                ),
                f"schema preflight rpc {signature}",
            )
            print(f"  [+] rpc {signature}")
        except Exception as exc:
            failures.append(f"rpc {signature}: {exc}")

    if failures:
        raise SchemaPreflightError(failures)

    print("Schema preflight passed.")
    return []
