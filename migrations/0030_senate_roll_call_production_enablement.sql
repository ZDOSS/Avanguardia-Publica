-- 0030_senate_roll_call_production_enablement.sql
--
-- Replace migration 0029's hard public barrier with a guarded service-role
-- wrapper and atomically enable the reviewed Senate database gates. Runtime
-- writes remain disabled by default and are manual-dispatch-only until a
-- separately reviewed production canary and post-canary audit succeed.
--
-- Unlike the House cutover, this migration needs only one transaction. The
-- migration 0029 public OID has never had a mutating body, cannot call the
-- owner-only helper, and is paired with two strict false catalog gates. There
-- is therefore no older Senate writer or pre-barrier client transaction to
-- drain. Function replacement, gate enablement, and the marker become visible
-- together at commit.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_ingestion_status text;
    v_source_write_status text;
    v_source_writes_enabled jsonb;
    v_source_write_rpc text;
    v_source_private_helper text;
    v_source_public_barrier text;
    v_endpoint_status text;
    v_endpoint_ingestion_status text;
    v_endpoint_write_status text;
    v_endpoint_writes_enabled jsonb;
    v_endpoint_write_rpc text;
    v_endpoint_public_barrier text;
    v_public_oid oid;
    v_private_oid oid;
    v_constraint_oid oid;
    v_table_name text;
    v_column record;
    v_privilege text;
    v_protected_tables text[] := ARRAY[
        'public.source_records',
        'public.legislative_roll_calls',
        'public.person_roll_call_votes',
        'public.source_catalog_sources',
        'public.source_catalog_endpoints'
    ];
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0030_senate_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION
            'migration 0030_senate_roll_call_production_enablement is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0029_senate_roll_call_provenance'
          AND migration_version = 29
          AND metadata -> 'production_writes_enabled' = 'false'::jsonb
    ) THEN
        RAISE EXCEPTION
            'migration 0029_senate_roll_call_provenance must be applied first with writes disabled'
            USING ERRCODE = '55000';
    END IF;

    -- Use the same source-then-endpoint lock order as the reviewed 0029 helper.
    SELECT
        status,
        repo_fit,
        metadata ->> 'ingestion_status',
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled',
        metadata ->> 'write_rpc',
        metadata ->> 'private_write_helper',
        metadata ->> 'public_write_barrier'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_ingestion_status,
        v_source_write_status,
        v_source_writes_enabled,
        v_source_write_rpc,
        v_source_private_helper,
        v_source_public_barrier
    FROM public.source_catalog_sources
    WHERE slug = 'senate-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog row is missing: senate-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        status,
        metadata ->> 'ingestion_status',
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled',
        metadata ->> 'write_rpc',
        metadata ->> 'public_write_barrier'
    INTO
        v_endpoint_status,
        v_endpoint_ingestion_status,
        v_endpoint_write_status,
        v_endpoint_writes_enabled,
        v_endpoint_write_rpc,
        v_endpoint_public_barrier
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: senate-roll-call-xml.lis-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_source_ingestion_status
            IS DISTINCT FROM 'write_contract_ready_disabled'
       OR v_endpoint_ingestion_status
            IS DISTINCT FROM 'write_contract_ready_disabled'
       OR v_source_write_status
            IS DISTINCT FROM 'disabled_pending_runtime_wiring'
       OR v_endpoint_write_status
            IS DISTINCT FROM 'disabled_pending_runtime_wiring'
       OR v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_source_write_rpc IS DISTINCT FROM 'upsert_senate_roll_call'
       OR v_endpoint_write_rpc IS DISTINCT FROM 'upsert_senate_roll_call'
       OR v_source_private_helper
            IS DISTINCT FROM 'upsert_senate_roll_call_0029'
       OR v_source_public_barrier IS DISTINCT FROM 'installed'
       OR v_endpoint_public_barrier IS DISTINCT FROM 'installed' THEN
        RAISE EXCEPTION
            'Senate production enablement expected the exact reviewed 0029 disabled barrier and strict false gates'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.source_systems
        WHERE key = 'senate-lis'
          AND display_name = 'U.S. Senate Legislative Information System'
          AND source_kind = 'government'
          AND trust_level = 'official'
          AND verified = true
    ) OR NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_source_system_links
        WHERE source_slug = 'senate-roll-call-xml'
          AND source_system_key = 'senate-lis'
          AND link_type = 'same_source'
    ) OR NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_source_system_links
        WHERE source_slug = 'senate-roll-call-xml'
          AND source_system_key = 'congress-legislators'
          AND link_type = 'identifier_source'
    ) THEN
        RAISE EXCEPTION
            'reviewed Senate source-system or identifier provenance has drifted'
            USING ERRCODE = '55000';
    END IF;

    v_public_oid := to_regprocedure(
        'public.upsert_senate_roll_call(jsonb,jsonb)'
    );
    v_private_oid := to_regprocedure(
        'public.upsert_senate_roll_call_0029(jsonb,jsonb)'
    );

    IF v_public_oid IS NULL OR v_private_oid IS NULL THEN
        RAISE EXCEPTION
            'migration 0029 Senate public barrier or private helper is missing'
            USING ERRCODE = '42883';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid = v_public_oid
          AND pg_get_userbyid(procedure.proowner) = current_user
          AND procedure.prosecdef
          AND procedure.provolatile = 'v'
          AND procedure.proconfig
                IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(procedure.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(procedure.prosrc, E'\r\n', E'\n')) =
                '83ebd8b6cf695c27c1061f29d73bbe69'
          AND has_function_privilege(
                'service_role',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'anon',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'authenticated',
                procedure.oid,
                'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'public migration 0029 Senate barrier differs from its reviewed owner/security/body/ACL contract'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid = v_private_oid
          AND pg_get_userbyid(procedure.proowner) = current_user
          AND procedure.prosecdef
          AND procedure.provolatile = 'v'
          AND procedure.proconfig
                IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(procedure.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(procedure.prosrc, E'\r\n', E'\n')) =
                '0bf895df560fb34593a6aa67624c4509'
          AND NOT has_function_privilege(
                'service_role',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'anon',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'authenticated',
                procedure.oid,
                'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'private migration 0029 Senate helper differs from its reviewed owner/security/body/ACL contract'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                procedure.proacl,
                acldefault('f', procedure.proowner)
            )
        ) AS acl
        WHERE procedure.oid = v_public_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee NOT IN (
                procedure.proowner,
                'service_role'::regrole::oid
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                procedure.proacl,
                acldefault('f', procedure.proowner)
            )
        ) AS acl
        WHERE procedure.oid = v_private_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee <> procedure.proowner
    ) THEN
        RAISE EXCEPTION
            'migration 0029 Senate function execute grants have drifted'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_depend AS dependency
        WHERE dependency.refclassid = 'pg_proc'::regclass
          AND dependency.refobjid IN (v_public_oid, v_private_oid)
    ) THEN
        RAISE EXCEPTION
            'migration 0029 Senate functions have an unexpected dependent object'
            USING ERRCODE = '55000';
    END IF;

    SELECT constraint_state.oid
    INTO v_constraint_oid
    FROM pg_constraint AS constraint_state
    WHERE constraint_state.conrelid = 'public.source_records'::regclass
      AND constraint_state.conname
            = 'source_records_senate_roll_call_contract'
      AND constraint_state.contype = 'c'
      AND constraint_state.convalidated;

    IF v_constraint_oid IS NULL
       OR md5(pg_get_constraintdef(v_constraint_oid, true))
            IS DISTINCT FROM '60788cc0382fbb9ee9885bce9663bd31' THEN
        RAISE EXCEPTION
            'validated Senate source-record constraint differs from the reviewed 0029 contract'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS index_state
        WHERE index_state.indexrelid = to_regclass(
                'public.uq_person_external_ids_bioguide_normalized'
              )
          AND index_state.indrelid
                = 'public.person_external_ids'::regclass
          AND index_state.indisunique
          AND index_state.indisvalid
          AND index_state.indisready
          AND index_state.indnkeyatts = 3
          AND index_state.indkey[0] = (
                SELECT attribute.attnum
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid
                        = 'public.person_external_ids'::regclass
                  AND attribute.attname = 'source_system_key'
                  AND NOT attribute.attisdropped
          )
          AND index_state.indkey[1] = (
                SELECT attribute.attnum
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid
                        = 'public.person_external_ids'::regclass
                  AND attribute.attname = 'external_id_type'
                  AND NOT attribute.attisdropped
          )
          AND index_state.indkey[2] = 0
          AND pg_catalog.pg_get_expr(
                index_state.indexprs,
                index_state.indrelid
              ) = 'upper(btrim(external_id))'
          AND pg_catalog.pg_get_expr(
                index_state.indpred,
                index_state.indrelid
              ) = (
                '((source_system_key = ''bioguide''::text) AND '
                '(external_id_type = ''bioguide_id''::text))'
              )
    ) THEN
        RAISE EXCEPTION
            'case-normalized Bioguide ownership index is missing or has drifted'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT upper(btrim(external_id))
        FROM public.person_external_ids
        WHERE source_system_key = 'bioguide'
          AND external_id_type = 'bioguide_id'
        GROUP BY upper(btrim(external_id))
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'case-equivalent Bioguide identity rows must be resolved before migration 0030'
            USING ERRCODE = '23505';
    END IF;

    -- Preserve migration 0027's direct-DML closure. The public security-definer
    -- RPC is the only application-role mutation path for these facts and gates.
    FOREACH v_table_name IN ARRAY v_protected_tables LOOP
        IF has_table_privilege(
            'service_role',
            v_table_name,
            'SELECT'
        ) IS DISTINCT FROM true THEN
            RAISE EXCEPTION
                'service-role SELECT privilege boundary has drifted for %',
                v_table_name
                USING ERRCODE = '42501';
        END IF;

        FOREACH v_privilege IN ARRAY ARRAY[
            'INSERT',
            'UPDATE',
            'DELETE',
            'TRUNCATE',
            'REFERENCES',
            'TRIGGER'
        ] LOOP
            IF has_table_privilege(
                'service_role',
                v_table_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service-role retains % privilege on %',
                    v_privilege,
                    v_table_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;

    FOR v_column IN
        SELECT
            format('%I.%I', columns.table_schema, columns.table_name)
                AS qualified_table_name,
            columns.column_name
        FROM information_schema.columns AS columns
        WHERE format('%I.%I', columns.table_schema, columns.table_name)
              = ANY(v_protected_tables)
        ORDER BY
            columns.table_schema,
            columns.table_name,
            columns.ordinal_position
    LOOP
        FOREACH v_privilege IN ARRAY ARRAY[
            'INSERT',
            'UPDATE',
            'REFERENCES'
        ] LOOP
            IF has_column_privilege(
                'service_role',
                v_column.qualified_table_name,
                v_column.column_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service-role retains column % privilege on %.%',
                    v_privilege,
                    v_column.qualified_table_name,
                    v_column.column_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;
END
$migration_preflight$;

-- Block concurrent controlled fact writers while the zero-Senate baseline is
-- rechecked and the public wrapper plus database gates are activated.
LOCK TABLE public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes,
    public.voting_records
IN SHARE ROW EXCLUSIVE MODE;

DO $zero_fact_baseline$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.source_records
        WHERE source_system_key = 'senate-lis'
           OR source_catalog_slug = 'senate-roll-call-xml'
           OR source_record_key
                ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$'
    ) OR EXISTS (
        SELECT 1
        FROM public.legislative_roll_calls
        WHERE chamber = 'senate'
           OR canonical_roll_call_key ~ '^senate:'
    ) OR EXISTS (
        SELECT 1
        FROM public.voting_records
        WHERE roll_call_id ~ '^senate:'
    ) THEN
        RAISE EXCEPTION
            'Senate production enablement expected zero preexisting official or legacy canonical Senate facts'
            USING ERRCODE = '55000';
    END IF;
END
$zero_fact_baseline$;

-- Preserve the public function OID and its service-role-only ACL. Preflight stays
-- non-mutating and independent of the migration marker and both gates. Every
-- write-shaped call reaches only the exact reviewed 0029 helper, which performs
-- full payload, identity, monotonic, gate, and stored-state validation.
CREATE OR REPLACE FUNCTION public.upsert_senate_roll_call(
    p_roll_call jsonb,
    p_member_votes jsonb
)
RETURNS TABLE (
    roll_call_source_record_id uuid,
    member_vote_count integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
#variable_conflict use_column
DECLARE
    v_result_roll_call_source_record_id uuid;
    v_result_member_vote_count integer;
BEGIN
    IF jsonb_typeof(p_roll_call) = 'object'
       AND COALESCE(p_roll_call ->> 'preflight', '') = 'true'
       AND p_member_votes = '[]'::jsonb THEN
        RETURN QUERY SELECT NULL::uuid, 0::integer;
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0030_senate_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION
            'Senate roll-call production enablement migration marker is missing'
            USING ERRCODE = '55000';
    END IF;

    BEGIN
        SELECT
            result.roll_call_source_record_id,
            result.member_vote_count
        INTO STRICT
            v_result_roll_call_source_record_id,
            v_result_member_vote_count
        FROM public.upsert_senate_roll_call_0029(
            p_roll_call,
            p_member_votes
        ) AS result;
    EXCEPTION
        WHEN no_data_found OR too_many_rows THEN
            RAISE EXCEPTION
                'private Senate write helper did not return exactly one confirmation row'
                USING ERRCODE = '55000';
    END;

    IF v_result_roll_call_source_record_id IS NULL
       OR v_result_member_vote_count
            IS DISTINCT FROM jsonb_array_length(p_member_votes) THEN
        RAISE EXCEPTION
            'private Senate write helper returned an incomplete confirmation'
            USING ERRCODE = '55000';
    END IF;

    RETURN QUERY SELECT
        v_result_roll_call_source_record_id,
        v_result_member_vote_count;
END;
$function$;

REVOKE ALL ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)
    TO service_role;

DO $wrapper_validation$
DECLARE
    v_public_oid oid := to_regprocedure(
        'public.upsert_senate_roll_call(jsonb,jsonb)'
    );
    v_private_oid oid := to_regprocedure(
        'public.upsert_senate_roll_call_0029(jsonb,jsonb)'
    );
    v_preflight_source_record_id uuid;
    v_preflight_member_count integer;
BEGIN
    IF v_public_oid IS NULL OR v_private_oid IS NULL THEN
        RAISE EXCEPTION
            'Senate production wrapper or migration 0029 helper is missing'
            USING ERRCODE = '42883';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid = v_public_oid
          AND pg_get_userbyid(procedure.proowner) = current_user
          AND procedure.prosecdef
          AND procedure.provolatile = 'v'
          AND procedure.proconfig
                IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(procedure.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(procedure.prosrc, E'\r\n', E'\n')) =
                '272267d03db8d40d3a1303db3a664b36'
          AND has_function_privilege(
                'service_role',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'anon',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'authenticated',
                procedure.oid,
                'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'public Senate production wrapper differs from its reviewed owner/security/body/ACL contract'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid = v_private_oid
          AND pg_get_userbyid(procedure.proowner) = current_user
          AND procedure.prosecdef
          AND procedure.provolatile = 'v'
          AND procedure.proconfig
                IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(procedure.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(procedure.prosrc, E'\r\n', E'\n')) =
                '0bf895df560fb34593a6aa67624c4509'
          AND NOT has_function_privilege(
                'service_role',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'anon',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege(
                'authenticated',
                procedure.oid,
                'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'private migration 0029 Senate helper changed during enablement'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                procedure.proacl,
                acldefault('f', procedure.proowner)
            )
        ) AS acl
        WHERE procedure.oid = v_public_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee NOT IN (
                procedure.proowner,
                'service_role'::regrole::oid
          )
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        CROSS JOIN LATERAL aclexplode(
            COALESCE(
                procedure.proacl,
                acldefault('f', procedure.proowner)
            )
        ) AS acl
        WHERE procedure.oid = v_private_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee <> procedure.proowner
    ) THEN
        RAISE EXCEPTION
            'Senate production function execute grants differ from the reviewed contract'
            USING ERRCODE = '42501';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_depend AS dependency
        WHERE dependency.refclassid = 'pg_proc'::regclass
          AND dependency.refobjid IN (v_public_oid, v_private_oid)
    ) THEN
        RAISE EXCEPTION
            'Senate production functions have an unexpected dependent object'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        result.roll_call_source_record_id,
        result.member_vote_count
    INTO STRICT
        v_preflight_source_record_id,
        v_preflight_member_count
    FROM public.upsert_senate_roll_call(
        jsonb_build_object('preflight', true),
        '[]'::jsonb
    ) AS result;

    IF v_preflight_source_record_id IS NOT NULL
       OR v_preflight_member_count IS DISTINCT FROM 0 THEN
        RAISE EXCEPTION
            'Senate production wrapper preflight contract is mutating or malformed'
            USING ERRCODE = '55000';
    END IF;
END
$wrapper_validation$;

DO $enablement$
DECLARE
    v_updated_rows integer;
BEGIN
    UPDATE public.source_catalog_sources
    SET metadata = metadata || jsonb_build_object(
        'ingestion_status', 'production_enabled_monotonic',
        'production_write_status', 'production_enabled_monotonic',
        'production_writes_enabled', true,
        'runtime_write_status', 'runtime_opt_in_required',
        'monotonic_guard_migration', '0029_senate_roll_call_provenance',
        'enablement_migration',
            '0030_senate_roll_call_production_enablement',
        'public_write_barrier', 'replaced_by_guarded_wrapper'
    )
    WHERE slug = 'senate-roll-call-xml';
    GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

    IF v_updated_rows <> 1 THEN
        RAISE EXCEPTION
            'Senate source gate enablement updated % rows, expected 1',
            v_updated_rows
            USING ERRCODE = '55000';
    END IF;

    UPDATE public.source_catalog_endpoints
    SET metadata = metadata || jsonb_build_object(
        'ingestion_status', 'production_enabled_monotonic',
        'production_write_status', 'production_enabled_monotonic',
        'production_writes_enabled', true,
        'runtime_write_status', 'runtime_opt_in_required',
        'monotonic_guard_migration', '0029_senate_roll_call_provenance',
        'enablement_migration',
            '0030_senate_roll_call_production_enablement',
        'public_write_barrier', 'replaced_by_guarded_wrapper'
    )
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed';
    GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

    IF v_updated_rows <> 1 THEN
        RAISE EXCEPTION
            'Senate endpoint gate enablement updated % rows, expected 1',
            v_updated_rows
            USING ERRCODE = '55000';
    END IF;
END
$enablement$;

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0030_senate_roll_call_production_enablement',
    30,
    'Install the guarded Senate write wrapper and atomically enable its reviewed database gates.',
    jsonb_build_object(
        'source_slug', 'senate-roll-call-xml',
        'endpoint_slug', 'lis-roll-call-feed',
        'write_rpc', 'upsert_senate_roll_call',
        'private_write_helper', 'upsert_senate_roll_call_0029',
        'pre_enablement_barrier_body_md5',
            '83ebd8b6cf695c27c1061f29d73bbe69',
        'private_write_helper_body_md5',
            '0bf895df560fb34593a6aa67624c4509',
        'production_wrapper_body_md5', '272267d03db8d40d3a1303db3a664b36',
        'senate_source_record_constraint_md5',
            '60788cc0382fbb9ee9885bce9663bd31',
        'function_reverse_dependencies_required', 0,
        'case_normalized_bioguide_unique', true,
        'monotonic_observations', true,
        'exact_replay_state_comparison', true,
        'trusted_lis_bioguide_crosswalk_required', true,
        'service_role_direct_dml_closed', true,
        'strict_json_boolean_gates', true,
        'single_transaction_activation', true,
        'preexisting_mutating_public_writer', false,
        'production_writes_enabled', true,
        'runtime_opt_in_required', true,
        'scheduled_runtime_writes_enabled', false,
        'manual_canary_required', true,
        'scraper_preflight_required', true
    )
);

DO $post_enablement_validation$
DECLARE
    v_source_writes_enabled jsonb;
    v_endpoint_writes_enabled jsonb;
BEGIN
    SELECT metadata -> 'production_writes_enabled'
    INTO v_source_writes_enabled
    FROM public.source_catalog_sources
    WHERE slug = 'senate-roll-call-xml';

    SELECT metadata -> 'production_writes_enabled'
    INTO v_endpoint_writes_enabled
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed';

    IF v_source_writes_enabled IS DISTINCT FROM 'true'::jsonb
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'true'::jsonb
       OR NOT EXISTS (
            SELECT 1
            FROM public.schema_migrations
            WHERE migration_key
                    = '0030_senate_roll_call_production_enablement'
              AND migration_version = 30
              AND metadata -> 'production_writes_enabled' = 'true'::jsonb
              AND metadata -> 'scheduled_runtime_writes_enabled'
                    = 'false'::jsonb
       ) THEN
        RAISE EXCEPTION
            'Senate production enablement marker or strict JSON-boolean gates failed validation'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.source_records
        WHERE source_system_key = 'senate-lis'
           OR source_catalog_slug = 'senate-roll-call-xml'
           OR source_record_key
                ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$'
    ) OR EXISTS (
        SELECT 1
        FROM public.legislative_roll_calls
        WHERE chamber = 'senate'
           OR canonical_roll_call_key ~ '^senate:'
    ) OR EXISTS (
        SELECT 1
        FROM public.voting_records
        WHERE roll_call_id ~ '^senate:'
    ) THEN
        RAISE EXCEPTION
            'migration 0030 unexpectedly wrote Senate facts while enabling gates'
            USING ERRCODE = '55000';
    END IF;
END
$post_enablement_validation$;

NOTIFY pgrst, 'reload schema';

COMMIT;
