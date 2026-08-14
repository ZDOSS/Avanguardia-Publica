-- 0036_congress_gov_scheduled_enablement.sql
--
-- Record the successful bounded Congress.gov production canary and its
-- post-canary database audit before the workflow opts scheduled events into
-- the already-reviewed private atomic writer. The detail and link caps,
-- exact-identifier contract, private ACLs, runtime defaults, and public-read
-- prohibition remain unchanged.

BEGIN;

SET LOCAL statement_timeout = '60s';

-- Serialize this review decision with migration/catalog changes and prevent a
-- concurrent writer from changing the audited canary baseline.
LOCK TABLE public.schema_migrations IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE
    public.source_catalog_sources,
    public.source_catalog_endpoints,
    public.source_catalog_review_events
    IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE
    public.source_records,
    public.legislative_measures,
    public.legislative_roll_call_measure_links,
    public.legislative_roll_calls,
    public.voting_records
    IN SHARE MODE;

DO $scheduled_enablement_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_ingestion_status text;
    v_source_production_writes text;
    v_source_scheduled_writes jsonb;
    v_endpoint_status text;
    v_endpoint_ingestion_status text;
    v_endpoint_production_writes text;
    v_endpoint_scheduled_writes text;
    v_source_record_count bigint;
    v_measure_count bigint;
    v_bill_count bigint;
    v_amendment_count bigint;
    v_link_count bigint;
    v_linked_roll_call_count bigint;
    v_writer_oid oid;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0036_congress_gov_scheduled_enablement'
    ) THEN
        RAISE EXCEPTION
            'migration 0036_congress_gov_scheduled_enablement is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0035_congress_gov_metadata_provenance'
          AND migration_version = 35
    ) THEN
        RAISE EXCEPTION
            'migration 0035_congress_gov_metadata_provenance must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF to_regclass('public.legislative_measures') IS NULL
       OR to_regclass('public.legislative_roll_call_measure_links') IS NULL THEN
        RAISE EXCEPTION 'Congress.gov private fact tables are missing'
            USING ERRCODE = '42P01';
    END IF;

    SELECT
        source.status,
        source.repo_fit,
        source.metadata ->> 'ingestion_status',
        source.metadata ->> 'production_writes_enabled',
        source.metadata -> 'scheduled_runtime_writes_enabled'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_ingestion_status,
        v_source_production_writes,
        v_source_scheduled_writes
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'congress-gov-api'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog row is missing: congress-gov-api'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        endpoint.status,
        endpoint.metadata ->> 'ingestion_status',
        endpoint.metadata ->> 'production_writes_enabled',
        endpoint.metadata ->> 'scheduled_runtime_writes_enabled'
    INTO
        v_endpoint_status,
        v_endpoint_ingestion_status,
        v_endpoint_production_writes,
        v_endpoint_scheduled_writes
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'congress-gov-api'
      AND endpoint.endpoint_slug = 'api-v3'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: congress-gov-api.api-v3'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_source_ingestion_status IS DISTINCT FROM
            'private_provenance_storage'
       OR v_source_production_writes IS DISTINCT FROM 'true'
       OR v_source_scheduled_writes IS NOT NULL
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_endpoint_ingestion_status IS DISTINCT FROM
            'private_provenance_storage'
       OR v_endpoint_production_writes IS DISTINCT FROM 'true'
       OR v_endpoint_scheduled_writes IS DISTINCT FROM 'false' THEN
        RAISE EXCEPTION
            'Congress.gov gates do not match the reviewed 0035 manual-canary boundary'
            USING ERRCODE = '55000';
    END IF;

    SELECT count(*)
    INTO v_source_record_count
    FROM public.source_records
    WHERE source_system_key = 'congress-gov'
       OR source_catalog_slug = 'congress-gov-api';

    SELECT
        count(*),
        count(*) FILTER (WHERE measure_kind = 'bill'),
        count(*) FILTER (WHERE measure_kind = 'amendment')
    INTO v_measure_count, v_bill_count, v_amendment_count
    FROM public.legislative_measures;

    SELECT count(*), count(DISTINCT roll_call_source_record_id)
    INTO v_link_count, v_linked_roll_call_count
    FROM public.legislative_roll_call_measure_links;

    IF v_source_record_count <> 18
       OR v_measure_count <> 18
       OR v_bill_count <> 15
       OR v_amendment_count <> 3
       OR v_link_count <> 43
       OR v_linked_roll_call_count <> 40 THEN
        RAISE EXCEPTION
            'Congress.gov canary counts differ from reviewed 18 source / 18 measure (15 bill, 3 amendment) / 43 link / 40 roll-call baseline: % / % (% bill, % amendment) / % / %',
            v_source_record_count,
            v_measure_count,
            v_bill_count,
            v_amendment_count,
            v_link_count,
            v_linked_roll_call_count
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.source_records AS source
        WHERE source.source_system_key = 'congress-gov'
           OR source.source_catalog_slug = 'congress-gov-api'
        GROUP BY source.id
        HAVING (
            bool_and(source.source_system_key = 'congress-gov')
            AND bool_and(source.record_type = 'legislative_measure')
            AND bool_and(source.person_id IS NULL)
            AND bool_and(source.legacy_politician_id IS NULL)
            AND bool_and(source.source_catalog_slug = 'congress-gov-api')
            AND bool_and(source.source_endpoint_slug = 'api-v3')
            AND bool_and(
                source.source_url = 'https://api.congress.gov/v3/' ||
                    replace(source.source_record_key, ':', '/')
            )
            AND bool_and(source.raw_payload_ref IS NULL)
            AND bool_and(source.payload_hash ~ '^[0-9a-f]{64}$')
            AND bool_and(source.verified_lane = 'verified')
            AND bool_and(source.record_status = 'active')
            AND bool_and(source.retired_at IS NULL)
            AND bool_and(
                source.first_seen_at >=
                    TIMESTAMPTZ '2026-08-14 20:17:00+00'
                AND source.first_seen_at <
                    TIMESTAMPTZ '2026-08-14 20:18:00+00'
            )
            AND bool_and(
                source.metadata = jsonb_build_object(
                    'ingestion_method',
                        'congress_gov_api_v3_exact_detail',
                    'raw_json_retained', false,
                    'measure_kind',
                        split_part(source.source_record_key, ':', 1)
                )
            )
        ) IS NOT TRUE
    ) THEN
        RAISE EXCEPTION
            'Congress.gov canary source provenance failed exact-contract audit'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.legislative_measures AS measure
        LEFT JOIN public.source_records AS source
          ON source.id = measure.source_record_id
        WHERE (
            source.id IS NOT NULL
            AND source.source_system_key = 'congress-gov'
            AND source.source_record_key = measure.canonical_measure_key
            AND source.record_type = 'legislative_measure'
            AND source.source_catalog_slug = 'congress-gov-api'
            AND source.source_endpoint_slug = 'api-v3'
            AND source.verified_lane = 'verified'
            AND source.record_status = 'active'
            AND measure.metadata = jsonb_build_object(
                'source', 'congress-gov-api',
                'raw_json_retained', false
            )
        ) IS NOT TRUE
    ) THEN
        RAISE EXCEPTION
            'Congress.gov normalized measures failed source-record or metadata audit'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.legislative_roll_call_measure_links AS link
        JOIN public.legislative_measures AS measure
          ON measure.source_record_id = link.measure_source_record_id
        JOIN public.source_records AS measure_source
          ON measure_source.id = measure.source_record_id
        JOIN public.legislative_roll_calls AS roll_call
          ON roll_call.source_record_id = link.roll_call_source_record_id
        JOIN public.source_records AS roll_call_source
          ON roll_call_source.id = roll_call.source_record_id
        WHERE (
            link.link_basis = 'exact_official_measure_identifier'
            AND measure.congress = roll_call.congress
            AND measure_source.source_system_key = 'congress-gov'
            AND measure_source.verified_lane = 'verified'
            AND measure_source.record_status = 'active'
            AND roll_call_source.verified_lane = 'verified'
            AND roll_call_source.record_status = 'active'
            AND (
                (
                    roll_call.chamber = 'house'
                    AND roll_call_source.source_system_key = 'house-clerk'
                    AND roll_call_source.source_catalog_slug =
                        'house-clerk-roll-call-xml'
                    AND roll_call_source.source_endpoint_slug =
                        'evs-roll-call-feed'
                )
                OR
                (
                    roll_call.chamber = 'senate'
                    AND roll_call_source.source_system_key = 'senate-lis'
                    AND roll_call_source.source_catalog_slug =
                        'senate-roll-call-xml'
                    AND roll_call_source.source_endpoint_slug =
                        'lis-roll-call-feed'
                )
            )
            AND link.metadata = jsonb_build_object(
                'join_policy',
                    'exact_official_roll_call_measure_identifier_only',
                'roll_call_source_record_key',
                    roll_call.canonical_roll_call_key,
                'measure_source_record_key',
                    measure.canonical_measure_key
            )
        ) IS NOT TRUE
    ) THEN
        RAISE EXCEPTION
            'Congress.gov exact roll-call links failed provenance or identity audit'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.voting_records AS vote
        JOIN public.legislative_measures AS measure
          ON vote.roll_call_id = measure.canonical_measure_key
          OR vote.bill_name = measure.canonical_measure_key
    ) THEN
        RAISE EXCEPTION
            'Congress.gov canonical measure keys must not appear in legacy voting_records'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relname IN (
              'legislative_measures',
              'legislative_roll_call_measure_links'
          )
          AND (
              NOT relation.relrowsecurity
              OR has_table_privilege('anon', relation.oid, 'SELECT')
              OR has_table_privilege(
                  'authenticated', relation.oid, 'SELECT'
              )
              OR NOT has_table_privilege(
                  'service_role', relation.oid, 'SELECT'
              )
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN (
              'legislative_measures',
              'legislative_roll_call_measure_links'
          )
    ) THEN
        RAISE EXCEPTION
            'Congress.gov fact tables no longer match the reviewed private ACL/RLS contract'
            USING ERRCODE = '42501';
    END IF;

    v_writer_oid := to_regprocedure(
        'public.upsert_congress_gov_measure_metadata(jsonb,jsonb)'
    );
    IF v_writer_oid IS NULL
       OR NOT EXISTS (
           SELECT 1
           FROM pg_proc
           WHERE oid = v_writer_oid
             AND prosecdef
             AND proconfig @> ARRAY['search_path=""']::text[]
       )
       OR has_function_privilege('anon', v_writer_oid, 'EXECUTE')
       OR has_function_privilege('authenticated', v_writer_oid, 'EXECUTE')
       OR NOT has_function_privilege('service_role', v_writer_oid, 'EXECUTE') THEN
        RAISE EXCEPTION
            'Congress.gov writer no longer matches the reviewed service-role-only contract'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'public'
          AND (
              definition ILIKE '%legislative_measures%'
              OR definition ILIKE
                  '%legislative_roll_call_measure_links%'
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc AS function
        JOIN pg_namespace AS namespace
          ON namespace.oid = function.pronamespace
        WHERE namespace.nspname = 'public'
          AND function.oid <> v_writer_oid
          AND (
              function.prosrc ILIKE '%legislative_measures%'
              OR function.prosrc ILIKE
                  '%legislative_roll_call_measure_links%'
          )
    ) THEN
        RAISE EXCEPTION
            'Congress.gov private facts unexpectedly gained another SQL read or write surface'
            USING ERRCODE = '42501';
    END IF;
END
$scheduled_enablement_preflight$;

DO $record_scheduled_approval$
DECLARE
    v_canary_evidence jsonb := jsonb_build_object(
        'reviewed_at', '2026-08-14',
        'manual_canary_run_id', 31833856216,
        'manual_canary_head_sha',
            '9d2d74e8c56fa8d7857096f312b8a72f2535440b',
        'schema_preflight_status', 'passed',
        'run_success', true,
        'duration_seconds', 4523.75,
        'house_roll_call_write_mode', 'disabled',
        'senate_roll_call_write_mode', 'disabled',
        'congress_gov_metadata_write_mode', 'enabled',
        'detail_attempts', 18,
        'detail_successes', 18,
        'detail_failures', 0,
        'distinct_bill_references', 15,
        'distinct_amendment_references', 3,
        'measure_rows_confirmed', 18,
        'exact_roll_call_measure_links_confirmed', 43,
        'linked_roll_calls_confirmed', 40,
        'write_attempts', 1,
        'write_successes', 1,
        'write_failures', 0,
        'database_audit_violations', 0,
        'legacy_measure_key_rows', 0,
        'raw_json_retained', false,
        'public_read_path_created', false,
        'exact_replay_count', 18,
        'exact_replay_link_count', 43,
        'exact_replay_row_images_changed', false,
        'exact_replay_transaction_ids_changed', false
    );
BEGIN
    UPDATE public.source_catalog_sources
    SET
        notes = 'Official Congress.gov API v3 approved for bounded scheduled exact-detail reconciliation into private provenance-backed tables. Collection crawling, raw JSON retention, public reads, fuzzy joins, and unbounded requests remain prohibited.',
        metadata = metadata || jsonb_build_object(
            'repo_usage_status',
                'Bounded private bill/amendment metadata writes enabled for reviewed nightly schedule events.',
            'repo_evidence',
                'The post-migration manual canary completed 18 of 18 exact detail requests, atomically confirmed 18 measures and 43 exact links, and passed provenance, ACL, legacy-isolation, and non-mutating replay audits.',
            'repo_next_action',
                'Review the first scheduled enabled runs before expanding the bounded window or adding a public read surface.',
            'scheduled_runtime_writes_enabled', true,
            'scheduled_enablement_review', v_canary_evidence
        )
    WHERE slug = 'congress-gov-api';

    UPDATE public.source_catalog_endpoints
    SET
        notes = 'Approved for at most 100 exact bill/amendment detail requests discovered in each bounded official roll-call window. Reviewed nightly schedules may write atomically to private facts; collection crawling and public reads remain prohibited.',
        metadata = metadata || jsonb_build_object(
            'scheduled_runtime_writes_enabled', true,
            'scheduled_enablement_review', v_canary_evidence
        )
    WHERE source_slug = 'congress-gov-api'
      AND endpoint_slug = 'api-v3';

    INSERT INTO public.source_catalog_review_events (
        source_slug,
        endpoint_slug,
        previous_status,
        new_status,
        reviewer,
        reason,
        evidence
    ) VALUES
        (
            'congress-gov-api',
            NULL,
            'approved',
            'approved',
            'phase-4-congress-gov-scheduled-enablement',
            'Permit the reviewed bounded private writer on nightly schedules after a successful manual canary and database audit.',
            v_canary_evidence || jsonb_build_object(
                'review_scope', 'source_scheduled_private_storage'
            )
        ),
        (
            'congress-gov-api',
            'api-v3',
            'approved',
            'approved',
            'phase-4-congress-gov-scheduled-enablement',
            'Permit only the existing capped exact-detail endpoint contract on nightly schedules.',
            v_canary_evidence || jsonb_build_object(
                'review_scope', 'endpoint_scheduled_private_storage'
            )
        );

    INSERT INTO public.schema_migrations (
        migration_key,
        migration_version,
        description,
        metadata
    ) VALUES (
        '0036_congress_gov_scheduled_enablement',
        36,
        'Record the audited Congress.gov write canary and approve the existing bounded private path for scheduled workflow events.',
        jsonb_build_object(
            'source_slug', 'congress-gov-api',
            'endpoint_slug', 'api-v3',
            'source_system_key', 'congress-gov',
            'runtime_default', 'disabled',
            'manual_input_default', 'disabled',
            'scheduled_runtime_writes_enabled', true,
            'unknown_events_enabled', false,
            'maximum_distinct_detail_requests_per_run', 100,
            'maximum_roll_call_links_per_run', 5000,
            'scraper_preflight_required', true,
            'raw_json_retained', false,
            'legacy_vote_writes_enabled', false,
            'public_read_path_created', false,
            'canary_evidence', v_canary_evidence
        )
    );
END
$record_scheduled_approval$;

NOTIFY pgrst, 'reload schema';

COMMIT;
