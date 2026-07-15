ZERO_UUID = "00000000-0000-0000-0000-000000000000"
REQUIRED_MIGRATION_KEY = "0023_source_inventory_context_seed"
REQUIRED_MIGRATION_FILE = "0023_source_inventory_context_seed.sql"

REQUIRED_COLUMN_CHECKS = [
    (
        "politicians",
        "id,full_name,current_office,party,state,district,external_ids,aliases,"
        "government_level,government_branch,office_type,jurisdiction,"
        "search_vector,last_updated,bioguide_id",
    ),
    (
        "contact_info",
        "politician_id,person_id,office_address,phone_number,official_website,last_updated",
    ),
    (
        "financial_disclosures",
        "politician_id,person_id,filing_type,filing_date,doc_id,doc_url",
    ),
    (
        "campaign_donors",
        "politician_id,person_id,donor_name,amount,donation_date,pac_status,"
        "fec_transaction_id",
    ),
    (
        "voting_records",
        "politician_id,person_id,bill_name,bill_summary,vote_cast,vote_date,roll_call_id,"
        "jurisdiction",
    ),
    (
        "relationships",
        "id,politician_id,person_id,related_name,relationship_type,source_api,url,"
        "last_updated,related_politician_id",
    ),
    (
        "unconfirmed_mentions",
        "politician_id,person_id,source_api,content_summary,url,sentiment_score",
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
    (
        "source_records",
        "id,source_system_key,source_record_key,record_type,person_id,"
        "legacy_politician_id,source_catalog_slug,source_endpoint_slug,source_url,"
        "raw_payload_ref,payload_hash,verified_lane,record_status,source_updated_at,"
        "first_seen_at,last_seen_at,retired_at,metadata,created_at,updated_at",
    ),
    (
        "person_office_terms",
        "id,person_id,source_record_id,source_term_key,legacy_politician_id,"
        "office_title,role_type,organization_name,government_level,government_branch,"
        "office_type,jurisdiction,state,district,term_start,term_end,term_status,"
        "metadata,created_at,updated_at",
    ),
    ("schema_migrations", "migration_key,applied_at"),
]

REQUIRED_RPC_CHECKS = [
    (
        "retire_source_profile_record",
        {
            "p_source_record_id": ZERO_UUID,
            "p_retired_at": None,
            "p_term_end": None,
        },
        "retire_source_profile_record(uuid, timestamptz, date)",
    ),
    (
        "upsert_source_profile_identity",
        {
            "p_source_system_key": "__preflight__",
            "p_source_record_key": "__preflight__",
            "p_profile": {"preflight": True},
            "p_trusted_external_ids": [],
            "p_source_url": None,
            "p_raw_payload_ref": None,
            "p_payload_hash": None,
            "p_verified_lane": "unverified",
            "p_office_term": None,
            "p_source_catalog_slug": None,
            "p_source_endpoint_slug": None,
            "p_source_updated_at": None,
        },
        "upsert_source_profile_identity(text, text, jsonb, jsonb, text, text, text, text, jsonb, text, text, timestamptz)",
    ),
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
    (
        "get_canonical_person_office_terms",
        {"p_id": ZERO_UUID},
        "get_canonical_person_office_terms(uuid)",
    ),
]


class SchemaPreflightError(RuntimeError):
    def __init__(self, failures: list[str]):
        self.failures = failures
        message = (
            "Supabase schema preflight failed. Apply only the next unapplied migration "
            f"(currently {REQUIRED_MIGRATION_FILE}) in the Supabase SQL editor; "
            "never replay migration history. Then run "
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

    try:
        marker = loader.execute_supabase(
            lambda: (
                loader.supabase.table("schema_migrations")
                .select("migration_key")
                .eq("migration_key", REQUIRED_MIGRATION_KEY)
                .limit(1)
                .execute()
            ),
            f"schema preflight migration marker {REQUIRED_MIGRATION_KEY}",
        )
        if not marker.data:
            failures.append(
                f"migration marker {REQUIRED_MIGRATION_KEY}: not found; apply {REQUIRED_MIGRATION_FILE}"
            )
        else:
            print(f"  [+] migration marker {REQUIRED_MIGRATION_KEY}")
    except Exception as exc:
        failures.append(f"migration marker {REQUIRED_MIGRATION_KEY}: {exc}")

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
