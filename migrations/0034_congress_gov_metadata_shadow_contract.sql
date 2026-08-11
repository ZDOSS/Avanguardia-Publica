-- 0034_congress_gov_metadata_shadow_contract.sql
--
-- Correct the seeded Congress.gov API v3 coordinates and record the bounded
-- bill/amendment metadata shadow contract. This migration deliberately keeps
-- the source and endpoint as review candidates until production-key observations
-- exist. It creates no legislative fact table, writer, RPC, or public read path.
-- Because the scraper can safely skip this optional source, schema preflight
-- remains on migration 0033.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_base_url text;
    v_endpoint_status text;
    v_endpoint_url text;
    v_source_system_display_name text;
    v_source_system_kind text;
    v_source_system_trust_level text;
    v_source_system_verified boolean;
    v_evidence jsonb := jsonb_build_object(
        'migration', '0034_congress_gov_metadata_shadow_contract',
        'contract_recorded_at', '2026-08-10',
        'api_base_url', 'https://api.congress.gov/v3/',
        'documentation_url', 'https://github.com/LibraryOfCongress/api.congress.gov/',
        'rights_url', 'https://www.congress.gov/help/using-data-offsite',
        'authentication', jsonb_build_object(
            'type', 'free_api_data_gov_key',
            'environment_variable', 'CONGRESS_GOV_API_KEY',
            'secret_value_stored_in_catalog', false,
            'demo_key_allowed_in_scheduled_pipeline', false
        ),
        'published_rate_limit_requests_per_hour', 5000,
        'request_scope', jsonb_build_object(
            'collection_endpoints_allowed', false,
            'bill_detail_path', '/bill/{congress}/{billType}/{billNumber}',
            'amendment_detail_path', '/amendment/{congress}/{amendmentType}/{amendmentNumber}',
            'maximum_distinct_detail_requests_per_run', 100,
            'upstream_roll_call_window_per_chamber', 25
        ),
        'join_policy', 'exact_official_roll_call_measure_identifier_only',
        'house_amendment_policy', 'skip_procedural_amendment_numbers_without_an_explicit_hamdt_identifier',
        'measure_source_record_key', '{kind}:{congress}:{measure_type}:{number}',
        'verified_lane', 'verified',
        'normalized_shadow_fields', jsonb_build_array(
            'title',
            'purpose',
            'description',
            'origin_chamber',
            'introduced_or_submitted_date',
            'update_date',
            'latest_action_date',
            'latest_action_text',
            'official_congress_gov_url',
            'amended_measure_identity'
        ),
        'retention', jsonb_build_object(
            'normalized_metadata', 'in_memory_shadow_only',
            'payload_hash', 'computed_in_memory_for_future_provenance_review',
            'raw_json', 'not_retained',
            'database_facts', 'not_written'
        ),
        'rights', jsonb_build_object(
            'classification', 'official_public_information',
            'reuse_basis', 'Congress.gov provides an API for the public to retrieve and reuse machine-readable legislative data.',
            'decision_status', 'pending_production_observation_before_catalog_approval'
        ),
        'health_policy', jsonb_build_object(
            'affects_run', false,
            'retry_server_failure_once', true,
            'stop_on_auth_quota_or_identity_conflict', true,
            'report_attempts_successes_failures_and_skips', true
        ),
        'production_write_status', 'disabled_pending_shadow_observation_and_separate_provenance_review'
    );
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0034_congress_gov_metadata_shadow_contract'
    ) THEN
        RAISE EXCEPTION
            'migration 0034_congress_gov_metadata_shadow_contract is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0033_official_voting_records_deduplication_repair'
          AND migration_version = 33
    ) THEN
        RAISE EXCEPTION
            'migration 0033_official_voting_records_deduplication_repair must be applied first'
            USING ERRCODE = '55000';
    END IF;

    SELECT status, repo_fit, base_url
    INTO v_source_status, v_source_repo_fit, v_source_base_url
    FROM public.source_catalog_sources
    WHERE slug = 'congress-gov-api'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog row is missing: congress-gov-api'
            USING ERRCODE = '23503';
    END IF;

    SELECT status, url
    INTO v_endpoint_status, v_endpoint_url
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'congress-gov-api'
      AND endpoint_slug = 'api-v3'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog endpoint is missing: congress-gov-api.api-v3'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'candidate'
       OR v_source_repo_fit IS DISTINCT FROM 'needs_review'
       OR v_endpoint_status IS DISTINCT FROM 'candidate' THEN
        RAISE EXCEPTION
            'Congress.gov shadow contract expected candidate/needs_review/candidate, found %/%/%',
            v_source_status,
            v_source_repo_fit,
            v_endpoint_status
            USING ERRCODE = '55000';
    END IF;

    IF v_source_base_url IS NULL OR v_source_base_url NOT IN (
        'https://api.data.gov/congress/v3/',
        'https://api.congress.gov/v3/'
    ) OR v_endpoint_url IS NULL OR v_endpoint_url NOT IN (
        'https://api.data.gov/congress/v3/',
        'https://api.congress.gov/v3/'
    ) THEN
        RAISE EXCEPTION
            'Congress.gov catalog coordinates changed outside the reviewed shadow contract: %/%',
            v_source_base_url,
            v_endpoint_url
            USING ERRCODE = '55000';
    END IF;

    INSERT INTO public.source_systems (
        key,
        display_name,
        source_kind,
        trust_level,
        verified,
        notes
    )
    VALUES (
        'congress-gov',
        'Congress.gov API',
        'government',
        'official',
        true,
        'Official Library of Congress legislative metadata namespace. Reserved by the bounded shadow contract; no source records are written at this migration boundary.'
    )
    ON CONFLICT (key) DO NOTHING;

    SELECT display_name, source_kind, trust_level, verified
    INTO
        v_source_system_display_name,
        v_source_system_kind,
        v_source_system_trust_level,
        v_source_system_verified
    FROM public.source_systems
    WHERE key = 'congress-gov'
    FOR UPDATE;

    IF v_source_system_display_name IS DISTINCT FROM 'Congress.gov API'
       OR v_source_system_kind IS DISTINCT FROM 'government'
       OR v_source_system_trust_level IS DISTINCT FROM 'official'
       OR v_source_system_verified IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            'congress-gov source system conflicts with the official shadow namespace: %/%/%/%',
            v_source_system_display_name,
            v_source_system_kind,
            v_source_system_trust_level,
            v_source_system_verified
            USING ERRCODE = '55000';
    END IF;

    UPDATE public.source_catalog_sources
    SET
        base_url = 'https://api.congress.gov/v3/',
        docs_url = 'https://github.com/LibraryOfCongress/api.congress.gov/',
        verified_at = DATE '2026-08-10',
        notes = 'Official Congress.gov API v3 candidate now wired only as a bounded bill/amendment detail shadow. Catalog approval and every database write remain pending production-key observations and a separate review.',
        metadata = metadata || jsonb_build_object(
            'repo_usage_status', 'Wired as a bounded detail-only metadata shadow; database writes disabled.',
            'repo_evidence', 'Fixture tests and a live API v3 contract probe validate exact bill and Senate-amendment identities; scheduled production-key observations are still required.',
            'repo_next_action', 'Provision CONGRESS_GOV_API_KEY, observe bounded scheduled shadow runs, then review normalized provenance storage in a separate slice.',
            'source_system_key', 'congress-gov',
            'ingestion_status', 'shadow_only',
            'source_review_status', 'pending_production_observation',
            'production_writes_enabled', false,
            'shadow_contract', v_evidence
        )
    WHERE slug = 'congress-gov-api';

    UPDATE public.source_catalog_endpoints
    SET
        url = 'https://api.congress.gov/v3/',
        docs_url = 'https://github.com/LibraryOfCongress/api.congress.gov/',
        notes = 'Candidate endpoint used only for exact bill/amendment detail requests discovered in the bounded official roll-call snapshots. Collection crawling and database writes are disabled.',
        metadata = metadata || jsonb_build_object(
            'ingestion_status', 'shadow_only',
            'collection_endpoints_allowed', false,
            'maximum_distinct_detail_requests_per_run', 100,
            'production_writes_enabled', false,
            'shadow_contract', v_evidence
        )
    WHERE source_slug = 'congress-gov-api'
      AND endpoint_slug = 'api-v3';

    INSERT INTO public.source_catalog_source_system_links (
        source_slug,
        source_system_key,
        link_type,
        notes
    )
    VALUES (
        'congress-gov-api',
        'congress-gov',
        'same_source',
        'Official Congress.gov API catalog entry and reserved source-record namespace.'
    )
    ON CONFLICT (source_slug, source_system_key, link_type) DO UPDATE SET
        notes = EXCLUDED.notes;

    INSERT INTO public.source_catalog_review_events (
        source_slug,
        endpoint_slug,
        previous_status,
        new_status,
        reviewer,
        reason,
        evidence
    )
    VALUES
        (
            'congress-gov-api',
            NULL,
            'candidate',
            'candidate',
            'phase-4-congress-gov-shadow-contract',
            'Record the bounded shadow and current API/reuse contract without approving production retention or writes.',
            v_evidence || jsonb_build_object('review_scope', 'source_shadow_contract')
        ),
        (
            'congress-gov-api',
            'api-v3',
            'candidate',
            'candidate',
            'phase-4-congress-gov-shadow-contract',
            'Record exact detail-only endpoint use; approval awaits production-key observations.',
            v_evidence || jsonb_build_object('review_scope', 'endpoint_shadow_contract')
        );

    INSERT INTO public.schema_migrations (
        migration_key,
        migration_version,
        description,
        metadata
    )
    VALUES (
        '0034_congress_gov_metadata_shadow_contract',
        34,
        'Correct Congress.gov API v3 catalog coordinates and record a bounded detail-only metadata shadow contract.',
        jsonb_build_object(
            'source_slug', 'congress-gov-api',
            'endpoint_slug', 'api-v3',
            'source_system_key', 'congress-gov',
            'source_status', 'candidate',
            'repo_fit', 'needs_review',
            'ingestion_status', 'shadow_only',
            'production_writes_enabled', false,
            'production_observation_required', true,
            'scraper_preflight_required', false
        )
    );
END
$migration$;

COMMIT;
