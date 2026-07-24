-- 0027_house_roll_call_production_enablement.sql
--
-- Harden official House roll-call observations against stale snapshots and
-- enable the reviewed database gates after a committed, fail-closed cutover
-- barrier. Runtime writes remain an explicit, disabled-by-default decision.
--
-- This migration intentionally uses two explicit transactions.
-- Do not pass --single-transaction to psql: phase one must commit the public RPC barrier
-- before phase two can prove that every transaction which could have observed
-- the migration 0026 body has drained. If phase two fails, both database gates
-- remain false and rerunning this same unapplied migration resumes safely from
-- the exact barrier/helper state.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_write_status text;
    v_source_writes_enabled jsonb;
    v_endpoint_status text;
    v_endpoint_write_status text;
    v_endpoint_writes_enabled jsonb;
    v_write_rpc_oid oid;
    v_write_rpc_owner text;
    v_write_rpc_security_definer boolean;
    v_write_rpc_volatility "char";
    v_write_rpc_config text[];
    v_write_rpc_result text;
    v_write_rpc_body_hash text;
    v_service_role_can_execute boolean;
    v_anon_can_execute boolean;
    v_authenticated_can_execute boolean;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0027_house_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION
            'migration 0027_house_roll_call_production_enablement is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0026_house_roll_call_provenance'
    ) THEN
        RAISE EXCEPTION
            'migration 0026_house_roll_call_provenance must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF current_setting('is_superuser')::boolean IS DISTINCT FROM true
       AND NOT pg_has_role(current_user, 'pg_read_all_stats', 'USAGE') THEN
        RAISE EXCEPTION
            'migration 0027 requires visibility into every client transaction via pg_read_all_stats'
            USING ERRCODE = '42501';
    END IF;

    SELECT
        status,
        repo_fit,
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_write_status,
        v_source_writes_enabled
    FROM public.source_catalog_sources
    WHERE slug = 'house-clerk-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog row is missing: house-clerk-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        status,
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled'
    INTO
        v_endpoint_status,
        v_endpoint_write_status,
        v_endpoint_writes_enabled
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: house-clerk-roll-call-xml.evs-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    -- A failed phase-two transaction leaves this exact committed barrier state.
    -- Accept it only as a resume point; phase two revalidates both function bodies,
    -- ACLs, metadata, and the transaction drain before changing any facts or gates.
    IF to_regprocedure(
        'public.upsert_house_roll_call_0026(jsonb,jsonb)'
    ) IS NOT NULL THEN
        IF v_source_status IS DISTINCT FROM 'approved'
           OR v_source_repo_fit IS DISTINCT FROM 'wired'
           OR v_endpoint_status IS DISTINCT FROM 'approved'
           OR v_source_write_status IS DISTINCT FROM 'cutover_barrier_installed'
           OR v_endpoint_write_status IS DISTINCT FROM 'cutover_barrier_installed'
           OR v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb
           OR v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb THEN
            RAISE EXCEPTION
                'House cutover resume expected the exact committed disabled barrier state'
                USING ERRCODE = '55000';
        END IF;
        RETURN;
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_source_write_status IS DISTINCT FROM 'disabled_pending_runtime_wiring'
       OR v_endpoint_write_status IS DISTINCT FROM 'disabled_pending_runtime_wiring'
       OR v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION
            'House production enablement expected approved/wired/approved with both write gates disabled, found %/%/% and %/% (%/%)',
            v_source_status,
            v_source_repo_fit,
            v_endpoint_status,
            v_source_write_status,
            v_endpoint_write_status,
            v_source_writes_enabled,
            v_endpoint_writes_enabled
            USING ERRCODE = '55000';
    END IF;

    SELECT
        p.oid,
        pg_get_userbyid(p.proowner),
        p.prosecdef,
        p.provolatile,
        p.proconfig,
        pg_get_function_result(p.oid),
        md5(replace(p.prosrc, E'\r\n', E'\n')),
        has_function_privilege('service_role', p.oid, 'EXECUTE'),
        has_function_privilege('anon', p.oid, 'EXECUTE'),
        has_function_privilege('authenticated', p.oid, 'EXECUTE')
    INTO
        v_write_rpc_oid,
        v_write_rpc_owner,
        v_write_rpc_security_definer,
        v_write_rpc_volatility,
        v_write_rpc_config,
        v_write_rpc_result,
        v_write_rpc_body_hash,
        v_service_role_can_execute,
        v_anon_can_execute,
        v_authenticated_can_execute
    FROM pg_proc AS p
    WHERE p.oid = to_regprocedure('public.upsert_house_roll_call(jsonb,jsonb)');

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required migration 0026 House write RPC is missing'
            USING ERRCODE = '42883';
    END IF;

    IF v_write_rpc_owner IS DISTINCT FROM current_user
       OR v_write_rpc_security_definer IS DISTINCT FROM true
       OR v_write_rpc_volatility IS DISTINCT FROM 'v'
       OR v_write_rpc_config IS DISTINCT FROM ARRAY['search_path=""']::text[]
       OR v_write_rpc_result IS DISTINCT FROM
            'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
       OR v_write_rpc_body_hash IS DISTINCT FROM 'dbd0d605e017550c959157926400d395'
       OR v_service_role_can_execute IS DISTINCT FROM true
       OR v_anon_can_execute IS DISTINCT FROM false
       OR v_authenticated_can_execute IS DISTINCT FROM false THEN
        RAISE EXCEPTION
            'migration 0026 House write RPC differs from the reviewed owner/security/body/ACL contract'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc AS p
        CROSS JOIN LATERAL aclexplode(
            COALESCE(p.proacl, acldefault('f', p.proowner))
        ) AS acl
        WHERE p.oid = v_write_rpc_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee NOT IN (
              p.proowner,
              'service_role'::regrole::oid
          )
    ) THEN
        RAISE EXCEPTION
            'migration 0026 House write RPC has an unexpected execute grantee'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_depend AS dependency
        WHERE dependency.refclassid = 'pg_proc'::regclass
          AND dependency.refobjid = v_write_rpc_oid
    ) THEN
        RAISE EXCEPTION
            'migration 0026 House write RPC has an unexpected dependent object'
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
            'case-equivalent Bioguide identity rows must be resolved before migration 0027'
            USING ERRCODE = '23505';
    END IF;

    IF to_regprocedure('public.upsert_house_roll_call_0026(jsonb,jsonb)') IS NOT NULL THEN
        RAISE EXCEPTION 'private migration 0026 House write helper already exists unexpectedly'
            USING ERRCODE = '55000';
    END IF;
END
$migration_preflight$;

-- Phase one preserves the reviewed 0026 implementation as an owner-only clone,
-- then replaces the same public function OID with a fail-closed barrier. Keeping
-- the OID closes prepared-plan/name-resolution gaps while the committed barrier
-- prevents every new service-role invocation from entering the old body.
DO $install_cutover_barrier$
DECLARE
    v_public_oid oid;
    v_public_definition text;
    v_private_definition text;
    v_updated_rows integer;
BEGIN
    IF to_regprocedure(
        'public.upsert_house_roll_call_0026(jsonb,jsonb)'
    ) IS NULL THEN
        SELECT p.oid, pg_get_functiondef(p.oid)
        INTO v_public_oid, v_public_definition
        FROM pg_proc AS p
        WHERE p.oid = to_regprocedure(
            'public.upsert_house_roll_call(jsonb,jsonb)'
        );

        IF NOT FOUND THEN
            RAISE EXCEPTION 'migration 0026 House write RPC disappeared during cutover'
                USING ERRCODE = '42883';
        END IF;

        v_private_definition := replace(
            v_public_definition,
            'FUNCTION public.upsert_house_roll_call(',
            'FUNCTION public.upsert_house_roll_call_0026('
        );
        IF v_private_definition IS NOT DISTINCT FROM v_public_definition THEN
            RAISE EXCEPTION 'could not derive the private migration 0026 helper definition'
                USING ERRCODE = '55000';
        END IF;

        EXECUTE v_private_definition;
        EXECUTE
            'REVOKE ALL PRIVILEGES ON FUNCTION '
            'public.upsert_house_roll_call_0026(jsonb,jsonb) '
            'FROM PUBLIC, anon, authenticated, service_role';

        EXECUTE $barrier_ddl$
            CREATE OR REPLACE FUNCTION public.upsert_house_roll_call(
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
            AS $barrier_function$
            BEGIN
                RAISE EXCEPTION
                    'House roll-call cutover barrier is active'
                    USING ERRCODE = '55000';
            END;
            $barrier_function$;
        $barrier_ddl$;

        EXECUTE
            'REVOKE ALL PRIVILEGES ON FUNCTION '
            'public.upsert_house_roll_call(jsonb,jsonb) '
            'FROM PUBLIC, anon, authenticated, service_role';
        EXECUTE
            'GRANT EXECUTE ON FUNCTION '
            'public.upsert_house_roll_call(jsonb,jsonb) TO service_role';

        UPDATE public.source_catalog_sources
        SET metadata = metadata || jsonb_build_object(
            'ingestion_status', 'cutover_barrier_installed',
            'production_write_status', 'cutover_barrier_installed',
            'production_writes_enabled', false,
            'runtime_write_status', 'disabled_for_database_cutover',
            'cutover_barrier_migration',
                '0027_house_roll_call_production_enablement',
            'cutover_barrier_installed_at', clock_timestamp()
        )
        WHERE slug = 'house-clerk-roll-call-xml';
        GET DIAGNOSTICS v_updated_rows = ROW_COUNT;
        IF v_updated_rows <> 1 THEN
            RAISE EXCEPTION 'House source cutover barrier updated % rows, expected 1',
                v_updated_rows
                USING ERRCODE = '55000';
        END IF;

        UPDATE public.source_catalog_endpoints
        SET metadata = metadata || jsonb_build_object(
            'ingestion_status', 'cutover_barrier_installed',
            'production_write_status', 'cutover_barrier_installed',
            'production_writes_enabled', false,
            'runtime_write_status', 'disabled_for_database_cutover',
            'cutover_barrier_migration',
                '0027_house_roll_call_production_enablement',
            'cutover_barrier_installed_at', clock_timestamp()
        )
        WHERE source_slug = 'house-clerk-roll-call-xml'
          AND endpoint_slug = 'evs-roll-call-feed';
        GET DIAGNOSTICS v_updated_rows = ROW_COUNT;
        IF v_updated_rows <> 1 THEN
            RAISE EXCEPTION 'House endpoint cutover barrier updated % rows, expected 1',
                v_updated_rows
                USING ERRCODE = '55000';
        END IF;
    END IF;
END
$install_cutover_barrier$;

-- Close every direct application mutation path in the same committed phase as
-- the public RPC barrier. The phase-two drain then covers calls or DML statements
-- which began while the migration-0026 privileges were still visible.
REVOKE ALL PRIVILEGES ON TABLE
    public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes,
    public.source_catalog_sources,
    public.source_catalog_endpoints
FROM service_role;

GRANT SELECT ON TABLE
    public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes,
    public.source_catalog_sources,
    public.source_catalog_endpoints
TO service_role;

DO $close_direct_dml$
DECLARE
    v_table text;
    v_column record;
    v_privilege text;
    v_tables text[] := ARRAY[
        'public.source_records',
        'public.legislative_roll_calls',
        'public.person_roll_call_votes',
        'public.source_catalog_sources',
        'public.source_catalog_endpoints'
    ];
BEGIN
    FOR v_column IN
        SELECT
            format('%I.%I', columns.table_schema, columns.table_name)
                AS qualified_table_name,
            columns.column_name
        FROM information_schema.columns AS columns
        WHERE format('%I.%I', columns.table_schema, columns.table_name)
              = ANY(v_tables)
        ORDER BY columns.table_schema, columns.table_name, columns.ordinal_position
    LOOP
        EXECUTE format(
            'REVOKE ALL PRIVILEGES (%I) ON TABLE %s FROM service_role',
            v_column.column_name,
            v_column.qualified_table_name
        );
    END LOOP;

    FOREACH v_table IN ARRAY v_tables LOOP
        IF has_table_privilege('service_role', v_table, 'SELECT') IS DISTINCT FROM true THEN
            RAISE EXCEPTION
                'service_role SELECT privilege closure failed for % during cutover',
                v_table
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
            IF has_table_privilege('service_role', v_table, v_privilege) THEN
                RAISE EXCEPTION
                    'service_role retains % privilege on % during cutover',
                    v_privilege,
                    v_table
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
              = ANY(v_tables)
        ORDER BY columns.table_schema, columns.table_name, columns.ordinal_position
    LOOP
        FOREACH v_privilege IN ARRAY ARRAY['INSERT', 'UPDATE', 'REFERENCES'] LOOP
            IF has_column_privilege(
                'service_role',
                v_column.qualified_table_name,
                v_column.column_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service_role retains column % privilege on %.% during cutover',
                    v_privilege,
                    v_column.qualified_table_name,
                    v_column.column_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;
END
$close_direct_dml$;

NOTIFY pgrst, 'reload schema';

COMMIT;

-- The committed public barrier is now visible to every new transaction. Capture
-- one fixed cutoff and drain every older client transaction, regardless of query
-- text, before phase two can lock or enable either gate.
BEGIN;

SET LOCAL statement_timeout = '30s';

DO $drain_pre_barrier_transactions$
DECLARE
    v_barrier_visible_at timestamptz := clock_timestamp();
    v_remaining_transactions integer;
BEGIN
    FOR v_attempt IN 1..100 LOOP
        SELECT count(*)
        INTO v_remaining_transactions
        FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND backend_type = 'client backend'
          AND xact_start IS NOT NULL
          AND xact_start <= v_barrier_visible_at;

        EXIT WHEN v_remaining_transactions = 0;
        PERFORM pg_sleep(0.1);
    END LOOP;

    IF v_remaining_transactions <> 0 THEN
        RAISE EXCEPTION
            'House cutover barrier could not drain % pre-barrier client transactions',
            v_remaining_transactions
            USING ERRCODE = '55000';
    END IF;
END
$drain_pre_barrier_transactions$;

DO $activation_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_write_status text;
    v_source_writes_enabled jsonb;
    v_source_barrier_migration text;
    v_endpoint_status text;
    v_endpoint_write_status text;
    v_endpoint_writes_enabled jsonb;
    v_endpoint_barrier_migration text;
    v_public_oid oid;
    v_private_oid oid;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0027_house_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION
            'migration 0027_house_roll_call_production_enablement is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0026_house_roll_call_provenance'
          AND migration_version = 26
    ) THEN
        RAISE EXCEPTION 'migration 0026_house_roll_call_provenance must be applied first'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        status,
        repo_fit,
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled',
        metadata ->> 'cutover_barrier_migration'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_write_status,
        v_source_writes_enabled,
        v_source_barrier_migration
    FROM public.source_catalog_sources
    WHERE slug = 'house-clerk-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required House source row disappeared after cutover barrier'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        status,
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled',
        metadata ->> 'cutover_barrier_migration'
    INTO
        v_endpoint_status,
        v_endpoint_write_status,
        v_endpoint_writes_enabled,
        v_endpoint_barrier_migration
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required House endpoint row disappeared after cutover barrier'
            USING ERRCODE = '23503';
    END IF;

    LOCK TABLE public.source_records,
        public.legislative_roll_calls,
        public.person_roll_call_votes
    IN SHARE ROW EXCLUSIVE MODE;

    IF EXISTS (
        SELECT 1
        FROM public.source_records
        WHERE source_system_key = 'house-clerk'
          AND (
              source_record_key
                  ~ '^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$'
              OR source_catalog_slug = 'house-clerk-roll-call-xml'
              OR source_endpoint_slug = 'evs-roll-call-feed'
          )
    ) OR EXISTS (
        SELECT 1
        FROM public.legislative_roll_calls
    ) OR EXISTS (
        SELECT 1
        FROM public.person_roll_call_votes
    ) THEN
        RAISE EXCEPTION
            'House production enablement expected zero preexisting House facts'
            USING ERRCODE = '55000';
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_source_write_status IS DISTINCT FROM 'cutover_barrier_installed'
       OR v_endpoint_write_status IS DISTINCT FROM 'cutover_barrier_installed'
       OR v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_source_barrier_migration IS DISTINCT FROM
            '0027_house_roll_call_production_enablement'
       OR v_endpoint_barrier_migration IS DISTINCT FROM
            '0027_house_roll_call_production_enablement' THEN
        RAISE EXCEPTION 'House production gates differ from the committed cutover barrier state'
            USING ERRCODE = '55000';
    END IF;

    v_public_oid := to_regprocedure(
        'public.upsert_house_roll_call(jsonb,jsonb)'
    );
    v_private_oid := to_regprocedure(
        'public.upsert_house_roll_call_0026(jsonb,jsonb)'
    );

    IF v_public_oid IS NULL OR v_private_oid IS NULL THEN
        RAISE EXCEPTION 'House cutover barrier or private 0026 helper is missing'
            USING ERRCODE = '42883';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS p
        WHERE p.oid = v_public_oid
          AND pg_get_userbyid(p.proowner) = current_user
          AND p.prosecdef
          AND p.provolatile = 'v'
          AND p.proconfig IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(p.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(p.prosrc, E'\r\n', E'\n')) =
                '684fd078d5d2149fe0950a0141cdd7b6'
          AND has_function_privilege('service_role', p.oid, 'EXECUTE')
          AND NOT has_function_privilege('anon', p.oid, 'EXECUTE')
          AND NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
    ) THEN
        RAISE EXCEPTION 'public House cutover barrier differs from its reviewed contract'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS p
        WHERE p.oid = v_private_oid
          AND pg_get_userbyid(p.proowner) = current_user
          AND p.prosecdef
          AND p.provolatile = 'v'
          AND p.proconfig IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND pg_get_function_result(p.oid) =
                'TABLE(roll_call_source_record_id uuid, member_vote_count integer)'
          AND md5(replace(p.prosrc, E'\r\n', E'\n')) =
                'dbd0d605e017550c959157926400d395'
          AND NOT has_function_privilege('service_role', p.oid, 'EXECUTE')
          AND NOT has_function_privilege('anon', p.oid, 'EXECUTE')
          AND NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
    ) THEN
        RAISE EXCEPTION 'private migration 0026 helper differs from its reviewed contract'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc AS p
        CROSS JOIN LATERAL aclexplode(
            COALESCE(p.proacl, acldefault('f', p.proowner))
        ) AS acl
        WHERE p.oid = v_public_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee NOT IN (p.proowner, 'service_role'::regrole::oid)
    ) OR EXISTS (
        SELECT 1
        FROM pg_proc AS p
        CROSS JOIN LATERAL aclexplode(
            COALESCE(p.proacl, acldefault('f', p.proowner))
        ) AS acl
        WHERE p.oid = v_private_oid
          AND acl.privilege_type = 'EXECUTE'
          AND acl.grantee <> p.proowner
    ) THEN
        RAISE EXCEPTION 'House cutover function ACLs differ from the reviewed contract'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_depend AS dependency
        WHERE dependency.refclassid = 'pg_proc'::regclass
          AND dependency.refobjid IN (v_public_oid, v_private_oid)
    ) THEN
        RAISE EXCEPTION 'House cutover functions have an unexpected dependent object'
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
            'case-equivalent Bioguide identity rows must be resolved before migration 0027'
            USING ERRCODE = '23505';
    END IF;
END
$activation_preflight$;

CREATE UNIQUE INDEX uq_person_external_ids_bioguide_normalized
    ON public.person_external_ids (
        source_system_key,
        external_id_type,
        upper(btrim(external_id))
    )
    WHERE source_system_key = 'bioguide'
      AND external_id_type = 'bioguide_id';

-- Other service-role RPCs also write source_records for person-profile lifecycle.
-- Constrain only the canonical House roll-call keyspace so those generic writers
-- cannot collide with this provenance contract while unrelated Clerk records remain
-- available for future reviewed uses.
ALTER TABLE public.source_records
    ADD CONSTRAINT source_records_house_roll_call_contract
    CHECK (
        NOT (
            source_system_key = 'house-clerk'
            AND source_record_key
                ~ '^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$'
        )
        OR (
            legacy_politician_id IS NULL
            AND source_catalog_slug = 'house-clerk-roll-call-xml'
            AND source_endpoint_slug = 'evs-roll-call-feed'
            AND source_url
                ~ '^https://clerk[.]house[.]gov/evs/[0-9]{4}/roll[0-9]+[.]xml$'
            AND raw_payload_ref IS NULL
            AND payload_hash ~ '^[0-9a-f]{64}$'
            AND verified_lane = 'verified'
            AND source_updated_at IS NULL
            AND NOT (metadata ? 'last_profile_name')
            AND NOT (metadata ? 'retirement_rpc_at')
            AND (
                (
                    source_record_key
                        ~ '^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*$'
                    AND record_type = 'legislative_roll_call'
                    AND person_id IS NULL
                    AND record_status = 'active'
                    AND retired_at IS NULL
                )
                OR (
                    source_record_key
                        ~ '^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*:[A-Z][0-9]{6}$'
                    AND record_type = 'person_roll_call_vote'
                    AND person_id IS NOT NULL
                    AND upper(btrim(metadata ->> 'bioguide_id'))
                        = substring(source_record_key FROM '([A-Z][0-9]{6})$')
                    AND (
                        (
                            record_status = 'active'
                            AND retired_at IS NULL
                        )
                        OR (
                            record_status = 'retired'
                            AND retired_at IS NOT NULL
                            AND metadata ->> 'retirement_reason'
                                = 'omitted_from_complete_house_roll_call_snapshot'
                            AND metadata ->> 'retired_by_payload_hash'
                                ~ '^[0-9a-f]{64}$'
                        )
                    )
                )
            )
        ) IS TRUE
    )
    NOT VALID;

ALTER TABLE public.source_records
    VALIDATE CONSTRAINT source_records_house_roll_call_contract;

CREATE OR REPLACE FUNCTION public.upsert_house_roll_call(
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
    v_congress integer;
    v_session smallint;
    v_congress_year integer;
    v_roll_call_number integer;
    v_vote_date date;
    v_question text;
    v_vote_result text;
    v_fetched_at timestamptz;
    v_payload_hash text;
    v_source_url text;
    v_url_parts text[];
    v_supplied_roll_call_key text;
    v_roll_call_key text;
    v_member_count integer;
    v_observation_fingerprint text;
    v_gate_source_status text;
    v_gate_source_repo_fit text;
    v_gate_source_writes_enabled jsonb;
    v_gate_endpoint_status text;
    v_gate_endpoint_writes_enabled jsonb;
    v_existing_roll_call_source_record_id uuid;
    v_existing_record_type text;
    v_existing_record_person_id uuid;
    v_existing_catalog_slug text;
    v_existing_endpoint_slug text;
    v_existing_source_url text;
    v_existing_raw_payload_ref text;
    v_existing_payload_hash text;
    v_existing_verified_lane text;
    v_existing_record_status text;
    v_existing_last_seen_at timestamptz;
    v_existing_retired_at timestamptz;
    v_existing_metadata jsonb;
    v_existing_roll_call_key text;
    v_existing_chamber text;
    v_existing_congress integer;
    v_existing_session smallint;
    v_existing_congress_year integer;
    v_existing_roll_call_number integer;
    v_existing_vote_date date;
    v_existing_question text;
    v_existing_vote_result text;
    v_existing_roll_call_metadata jsonb;
    v_existing_active_member_count integer;
    v_result_roll_call_source_record_id uuid;
    v_result_member_vote_count integer;
    v_updated_rows integer;
BEGIN
    -- Keep schema preflight non-mutating and independent of both production gates.
    IF jsonb_typeof(p_roll_call) = 'object'
       AND COALESCE(p_roll_call ->> 'preflight', '') = 'true'
       AND p_member_votes = '[]'::jsonb THEN
        RETURN QUERY SELECT NULL::uuid, 0::integer;
        RETURN;
    END IF;

    IF jsonb_typeof(p_roll_call) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'roll_call must be a JSON object' USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(p_member_votes) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'member_votes must be a JSON array' USING ERRCODE = '22023';
    END IF;

    v_member_count := jsonb_array_length(p_member_votes);
    IF v_member_count = 0 OR v_member_count > 1000 THEN
        RAISE EXCEPTION 'member_votes must contain between 1 and 1000 votes'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'bioguide_id'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'vote_cast'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '') IS NULL
    ) THEN
        RAISE EXCEPTION
            'every member vote must contain bioguide_id, vote_cast, and source_record_key'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT upper(btrim(item.value ->> 'bioguide_id')))
        FROM jsonb_array_elements(p_member_votes) AS item(value)
    ) <> v_member_count THEN
        RAISE EXCEPTION 'member_votes contains duplicate Bioguide IDs'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_congress := NULLIF(btrim(p_roll_call ->> 'congress'), '')::integer;
        v_session := NULLIF(btrim(p_roll_call ->> 'session'), '')::smallint;
        v_congress_year := NULLIF(btrim(p_roll_call ->> 'congress_year'), '')::integer;
        v_roll_call_number := NULLIF(btrim(p_roll_call ->> 'roll_call_number'), '')::integer;
        v_vote_date := NULLIF(btrim(p_roll_call ->> 'vote_date'), '')::date;
        v_fetched_at := NULLIF(btrim(p_roll_call ->> 'fetched_at'), '')::timestamptz;
    EXCEPTION
        WHEN invalid_text_representation OR datetime_field_overflow THEN
            RAISE EXCEPTION 'roll_call has an invalid identity, date, or timestamp field'
                USING ERRCODE = '22023';
    END;

    v_supplied_roll_call_key := NULLIF(
        btrim(p_roll_call ->> 'source_record_key'),
        ''
    );
    v_payload_hash := lower(NULLIF(btrim(p_roll_call ->> 'payload_hash'), ''));
    v_source_url := NULLIF(btrim(p_roll_call ->> 'source_url'), '');
    v_question := NULLIF(btrim(p_roll_call ->> 'question'), '');
    v_vote_result := NULLIF(btrim(p_roll_call ->> 'vote_result'), '');

    IF v_congress IS NULL
       OR v_congress <= 0
       OR v_session IS NULL
       OR v_session NOT IN (1, 2)
       OR v_congress_year IS NULL
       OR v_congress_year NOT BETWEEN 1789 AND 2200
       OR v_roll_call_number IS NULL
       OR v_roll_call_number <= 0
       OR v_vote_date IS NULL
       OR EXTRACT(YEAR FROM v_vote_date)::integer <> v_congress_year
       OR v_question IS NULL
       OR v_fetched_at IS NULL
       OR v_payload_hash IS NULL
       OR v_source_url IS NULL THEN
        RAISE EXCEPTION 'roll_call is missing a required monotonic-observation field'
            USING ERRCODE = '22023';
    END IF;

    IF v_payload_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'roll_call.payload_hash must be a SHA-256 hex digest'
            USING ERRCODE = '22023';
    END IF;

    IF v_fetched_at < v_vote_date::timestamptz
       OR v_fetched_at > now() + interval '5 minutes' THEN
        RAISE EXCEPTION 'roll_call.fetched_at is outside the valid observation window'
            USING ERRCODE = '22023';
    END IF;

    v_roll_call_key := format(
        'house:%s:%s:%s',
        v_congress,
        v_congress_year,
        v_roll_call_number
    );
    IF v_supplied_roll_call_key IS DISTINCT FROM v_roll_call_key THEN
        RAISE EXCEPTION
            'roll_call.source_record_key must equal the canonical House key %',
            v_roll_call_key
            USING ERRCODE = '22023';
    END IF;

    v_url_parts := regexp_match(
        v_source_url,
        '^https://clerk[.]house[.]gov/evs/([0-9]{4})/roll([0-9]+)[.]xml$'
    );
    IF v_url_parts IS NULL
       OR v_url_parts[1]::integer <> v_congress_year
       OR v_url_parts[2]::integer <> v_roll_call_number THEN
        RAISE EXCEPTION
            'roll_call.source_url must be the matching official House Clerk XML URL'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE upper(btrim(item.value ->> 'bioguide_id')) !~ '^[A-Z][0-9]{6}$'
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '')
                IS DISTINCT FROM format(
                    '%s:%s',
                    v_roll_call_key,
                    upper(btrim(item.value ->> 'bioguide_id'))
                )
           OR CASE lower(regexp_replace(
                btrim(item.value ->> 'vote_cast'),
                '[[:space:]_-]+',
                ' ',
                'g'
           ))
                WHEN 'aye' THEN 'yea'
                WHEN 'yes' THEN 'yea'
                WHEN 'yea' THEN 'yea'
                WHEN 'no' THEN 'nay'
                WHEN 'nay' THEN 'nay'
                WHEN 'present' THEN 'present'
                WHEN 'not voting' THEN 'not_voting'
                ELSE NULL
           END IS NULL
    ) THEN
        RAISE EXCEPTION 'member_votes contains an invalid ID, key, or vote cast'
            USING ERRCODE = '22023';
    END IF;

    -- JSONB object text is canonicalized. Array order is retained, and retries in
    -- the loader replay the exact same built payload. Pair that argument digest
    -- with the official raw-byte SHA-256 to identify an exact observation retry.
    v_observation_fingerprint := concat(
        v_payload_hash,
        ':',
        md5(p_roll_call::text || E'\n' || p_member_votes::text)
    );

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0027_house_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION 'House production enablement migration marker is missing'
            USING ERRCODE = '55000';
    END IF;

    -- Use the same source/endpoint/advisory lock order as migration 0026.
    SELECT
        source.status,
        source.repo_fit,
        source.metadata -> 'production_writes_enabled'
    INTO
        v_gate_source_status,
        v_gate_source_repo_fit,
        v_gate_source_writes_enabled
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'house-clerk-roll-call-xml'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'House roll-call source catalog row is missing'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        endpoint.status,
        endpoint.metadata -> 'production_writes_enabled'
    INTO
        v_gate_endpoint_status,
        v_gate_endpoint_writes_enabled
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'house-clerk-roll-call-xml'
      AND endpoint.endpoint_slug = 'evs-roll-call-feed'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'House roll-call source catalog endpoint is missing'
            USING ERRCODE = '23503';
    END IF;

    IF v_gate_source_status IS DISTINCT FROM 'approved'
       OR v_gate_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_gate_endpoint_status IS DISTINCT FROM 'approved'
       OR v_gate_source_writes_enabled IS DISTINCT FROM 'true'::jsonb
       OR v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION
            'authoritative House roll-call writes are disabled in the source catalog'
            USING ERRCODE = '55000';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(v_roll_call_key, 0));

    SELECT
        source.id,
        source.record_type,
        source.person_id,
        source.source_catalog_slug,
        source.source_endpoint_slug,
        source.source_url,
        source.raw_payload_ref,
        source.payload_hash,
        source.verified_lane,
        source.record_status,
        source.last_seen_at,
        source.retired_at,
        source.metadata
    INTO
        v_existing_roll_call_source_record_id,
        v_existing_record_type,
        v_existing_record_person_id,
        v_existing_catalog_slug,
        v_existing_endpoint_slug,
        v_existing_source_url,
        v_existing_raw_payload_ref,
        v_existing_payload_hash,
        v_existing_verified_lane,
        v_existing_record_status,
        v_existing_last_seen_at,
        v_existing_retired_at,
        v_existing_metadata
    FROM public.source_records AS source
    WHERE source.source_system_key = 'house-clerk'
      AND source.source_record_key = v_roll_call_key
    FOR UPDATE;

    IF FOUND THEN
        IF v_existing_record_type IS DISTINCT FROM 'legislative_roll_call'
           OR v_existing_record_person_id IS NOT NULL
           OR v_existing_catalog_slug IS DISTINCT FROM 'house-clerk-roll-call-xml'
           OR v_existing_endpoint_slug IS DISTINCT FROM 'evs-roll-call-feed'
           OR v_existing_raw_payload_ref IS NOT NULL
           OR v_existing_verified_lane IS DISTINCT FROM 'verified'
           OR v_existing_record_status IS DISTINCT FROM 'active'
           OR v_existing_last_seen_at IS NULL
           OR v_existing_retired_at IS NOT NULL THEN
            RAISE EXCEPTION
                'existing House roll-call source record conflicts with the production provenance contract'
                USING ERRCODE = '23505';
        END IF;

        SELECT
            roll_call.canonical_roll_call_key,
            roll_call.chamber,
            roll_call.congress,
            roll_call.session,
            roll_call.congress_year,
            roll_call.roll_call_number,
            roll_call.vote_date,
            roll_call.question,
            roll_call.vote_result,
            roll_call.metadata
        INTO
            v_existing_roll_call_key,
            v_existing_chamber,
            v_existing_congress,
            v_existing_session,
            v_existing_congress_year,
            v_existing_roll_call_number,
            v_existing_vote_date,
            v_existing_question,
            v_existing_vote_result,
            v_existing_roll_call_metadata
        FROM public.legislative_roll_calls AS roll_call
        WHERE roll_call.source_record_id = v_existing_roll_call_source_record_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'existing House roll-call source record is missing its normalized fact'
                USING ERRCODE = '23503';
        END IF;

        IF v_existing_roll_call_key IS DISTINCT FROM v_roll_call_key
           OR v_existing_chamber IS DISTINCT FROM 'house'
           OR v_existing_congress IS DISTINCT FROM v_congress
           OR v_existing_congress_year IS DISTINCT FROM v_congress_year
           OR v_existing_roll_call_number IS DISTINCT FROM v_roll_call_number THEN
            RAISE EXCEPTION
                'existing normalized House roll call conflicts with its stable event identity'
                USING ERRCODE = '23505';
        END IF;

        IF v_fetched_at < v_existing_last_seen_at THEN
            RAISE EXCEPTION
                'stale House roll-call observation for %: fetched_at % precedes stored %',
                v_roll_call_key,
                v_fetched_at,
                v_existing_last_seen_at
                USING ERRCODE = '55000';
        END IF;

        IF v_fetched_at = v_existing_last_seen_at THEN
            IF v_existing_payload_hash IS DISTINCT FROM v_payload_hash
               OR v_existing_source_url IS DISTINCT FROM v_source_url
               OR (v_existing_metadata ->> 'ingestion_method')
                    IS DISTINCT FROM 'house_clerk_roll_call_xml'
               OR (v_existing_metadata -> 'raw_xml_retained')
                    IS DISTINCT FROM 'false'::jsonb
               OR (v_existing_metadata ->> 'chamber') IS DISTINCT FROM 'house'
               OR (v_existing_metadata ->> 'observation_fingerprint')
                    IS DISTINCT FROM v_observation_fingerprint
               OR (v_existing_metadata ->> 'observation_fingerprint_version')
                    IS DISTINCT FROM 'payload_sha256_plus_jsonb_args_md5_v1'
               OR (v_existing_metadata ->> 'monotonic_guard_migration')
                    IS DISTINCT FROM '0027_house_roll_call_production_enablement' THEN
                RAISE EXCEPTION
                    'conflicting House roll-call observation timestamp for % at %',
                    v_roll_call_key,
                    v_fetched_at
                    USING ERRCODE = '23505';
            END IF;

            IF v_existing_session IS DISTINCT FROM v_session
               OR v_existing_vote_date IS DISTINCT FROM v_vote_date
               OR v_existing_question IS DISTINCT FROM v_question
               OR v_existing_vote_result IS DISTINCT FROM v_vote_result
               OR (v_existing_roll_call_metadata ->> 'source')
                    IS DISTINCT FROM 'house-clerk-roll-call-xml' THEN
                RAISE EXCEPTION
                    'conflicting House roll-call observation timestamp for % has normalized parent drift',
                    v_roll_call_key
                    USING ERRCODE = '23505';
            END IF;

            PERFORM 1
            FROM public.person_external_ids AS external_id
            JOIN public.people AS person ON person.id = external_id.person_id
            WHERE external_id.source_system_key = 'bioguide'
              AND external_id.external_id_type = 'bioguide_id'
              AND upper(btrim(external_id.external_id)) IN (
                  SELECT upper(btrim(item.value ->> 'bioguide_id'))
                  FROM jsonb_array_elements(p_member_votes) AS item(value)
              )
            ORDER BY external_id.person_id
            FOR SHARE OF external_id, person;

            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements(p_member_votes) AS item(value)
                WHERE (
                    SELECT count(*)
                    FROM public.person_external_ids AS external_id
                    JOIN public.people AS person ON person.id = external_id.person_id
                    WHERE external_id.source_system_key = 'bioguide'
                      AND external_id.external_id_type = 'bioguide_id'
                      AND upper(btrim(external_id.external_id))
                            = upper(btrim(item.value ->> 'bioguide_id'))
                ) <> 1
                   OR NOT EXISTS (
                        SELECT 1
                        FROM public.person_external_ids AS external_id
                        JOIN public.people AS person ON person.id = external_id.person_id
                        WHERE external_id.source_system_key = 'bioguide'
                          AND external_id.external_id_type = 'bioguide_id'
                          AND upper(btrim(external_id.external_id))
                                = upper(btrim(item.value ->> 'bioguide_id'))
                          AND external_id.is_trusted = true
                          AND person.status = 'active'
                   )
            ) THEN
                RAISE EXCEPTION
                    'exact House replay no longer resolves every Bioguide ID to one trusted active person'
                    USING ERRCODE = '23503';
            END IF;

            -- Lock the complete current active child state before proving that a
            -- same-timestamp call can return without firing any update trigger.
            PERFORM 1
            FROM public.source_records AS member_source
            WHERE member_source.record_status = 'active'
              AND (
                  member_source.source_record_key LIKE v_roll_call_key || ':%'
                  OR member_source.id IN (
                      SELECT vote.source_record_id
                      FROM public.person_roll_call_votes AS vote
                      WHERE vote.roll_call_source_record_id
                            = v_existing_roll_call_source_record_id
                  )
              )
            ORDER BY member_source.id
            FOR UPDATE;

            PERFORM 1
            FROM public.person_roll_call_votes AS vote
            WHERE vote.roll_call_source_record_id = v_existing_roll_call_source_record_id
            ORDER BY vote.source_record_id
            FOR UPDATE;

            SELECT count(*)::integer
            INTO v_existing_active_member_count
            FROM public.source_records AS member_source
            JOIN public.person_roll_call_votes AS vote
              ON vote.source_record_id = member_source.id
            WHERE vote.roll_call_source_record_id = v_existing_roll_call_source_record_id
              AND member_source.source_system_key = 'house-clerk'
              AND member_source.record_type = 'person_roll_call_vote'
              AND member_source.record_status = 'active';

            IF v_existing_active_member_count IS DISTINCT FROM v_member_count THEN
                RAISE EXCEPTION
                    'conflicting House roll-call observation timestamp for % has % active votes, not %',
                    v_roll_call_key,
                    v_existing_active_member_count,
                    v_member_count
                    USING ERRCODE = '23505';
            END IF;

            IF EXISTS (
                WITH incoming_state AS (
                    SELECT
                        btrim(item.value ->> 'source_record_key') AS source_record_key,
                        upper(btrim(item.value ->> 'bioguide_id')) AS bioguide_id,
                        'house_clerk_roll_call_xml'::text AS member_ingestion_method,
                        'false'::jsonb AS member_raw_xml_retained,
                        (
                            SELECT external_id.person_id
                            FROM public.person_external_ids AS external_id
                            JOIN public.people AS person
                              ON person.id = external_id.person_id
                            WHERE external_id.source_system_key = 'bioguide'
                              AND external_id.external_id_type = 'bioguide_id'
                              AND upper(btrim(external_id.external_id))
                                    = upper(btrim(item.value ->> 'bioguide_id'))
                              AND external_id.is_trusted = true
                              AND person.status = 'active'
                        ) AS person_id,
                        CASE lower(regexp_replace(
                            btrim(item.value ->> 'vote_cast'),
                            '[[:space:]_-]+',
                            ' ',
                            'g'
                        ))
                            WHEN 'aye' THEN 'yea'
                            WHEN 'yes' THEN 'yea'
                            WHEN 'yea' THEN 'yea'
                            WHEN 'no' THEN 'nay'
                            WHEN 'nay' THEN 'nay'
                            WHEN 'present' THEN 'present'
                            WHEN 'not voting' THEN 'not_voting'
                        END AS vote_cast,
                        upper(btrim(item.value ->> 'bioguide_id'))
                            AS vote_metadata_bioguide_id,
                        'house-clerk'::text AS source_system_key,
                        'person_roll_call_vote'::text AS record_type,
                        'house-clerk-roll-call-xml'::text AS source_catalog_slug,
                        'evs-roll-call-feed'::text AS source_endpoint_slug,
                        v_source_url AS source_url,
                        NULL::text AS raw_payload_ref,
                        v_payload_hash AS payload_hash,
                        'verified'::text AS verified_lane,
                        'active'::text AS record_status,
                        NULL::timestamptz AS retired_at,
                        v_fetched_at AS last_seen_at,
                        true AS vote_source_matches,
                        true AS vote_roll_call_matches,
                        true AS vote_person_matches
                    FROM jsonb_array_elements(p_member_votes) AS item(value)
                ),
                actual_state AS (
                    SELECT
                        member_source.source_record_key,
                        upper(btrim(member_source.metadata ->> 'bioguide_id'))
                            AS bioguide_id,
                        member_source.metadata ->> 'ingestion_method'
                            AS member_ingestion_method,
                        member_source.metadata -> 'raw_xml_retained'
                            AS member_raw_xml_retained,
                        member_source.person_id,
                        vote.vote_cast,
                        upper(btrim(vote.metadata ->> 'bioguide_id'))
                            AS vote_metadata_bioguide_id,
                        member_source.source_system_key,
                        member_source.record_type,
                        member_source.source_catalog_slug,
                        member_source.source_endpoint_slug,
                        member_source.source_url,
                        member_source.raw_payload_ref,
                        member_source.payload_hash,
                        member_source.verified_lane,
                        member_source.record_status,
                        member_source.retired_at,
                        member_source.last_seen_at,
                        vote.source_record_id = member_source.id AS vote_source_matches,
                        vote.roll_call_source_record_id
                            = v_existing_roll_call_source_record_id AS vote_roll_call_matches,
                        vote.person_id = member_source.person_id AS vote_person_matches
                    FROM public.source_records AS member_source
                    LEFT JOIN public.person_roll_call_votes AS vote
                      ON vote.source_record_id = member_source.id
                    WHERE member_source.record_status = 'active'
                      AND (
                          vote.roll_call_source_record_id
                                = v_existing_roll_call_source_record_id
                          OR (
                              member_source.source_system_key = 'house-clerk'
                              AND member_source.source_record_key
                                    LIKE v_roll_call_key || ':%'
                          )
                      )
                )
                SELECT 1
                FROM (
                    (SELECT * FROM incoming_state
                     EXCEPT
                     SELECT * FROM actual_state)
                    UNION ALL
                    (SELECT * FROM actual_state
                     EXCEPT
                     SELECT * FROM incoming_state)
                ) AS state_delta
            ) THEN
                RAISE EXCEPTION
                    'conflicting House roll-call observation timestamp for % has a different active House member-vote set',
                    v_roll_call_key
                    USING ERRCODE = '23505';
            END IF;

            RETURN QUERY SELECT
                v_existing_roll_call_source_record_id,
                v_existing_active_member_count;
            RETURN;
        END IF;
    END IF;

    -- This owner-only helper contains the reviewed atomic migration 0026 write.
    -- No call can reach it until the source row lock and monotonic guard above pass.
    BEGIN
        SELECT
            result.roll_call_source_record_id,
            result.member_vote_count
        INTO STRICT
            v_result_roll_call_source_record_id,
            v_result_member_vote_count
        FROM public.upsert_house_roll_call_0026(
            p_roll_call,
            p_member_votes
        ) AS result;
    EXCEPTION
        WHEN no_data_found OR too_many_rows THEN
            RAISE EXCEPTION
                'private House write helper did not return exactly one confirmation row'
                USING ERRCODE = '55000';
    END;

    IF v_result_member_vote_count IS DISTINCT FROM v_member_count THEN
        RAISE EXCEPTION
            'private House write helper confirmed % votes, expected %',
            v_result_member_vote_count,
            v_member_count
            USING ERRCODE = '55000';
    END IF;

    UPDATE public.source_records
    SET metadata = metadata || jsonb_build_object(
        'observation_fingerprint', v_observation_fingerprint,
        'observation_fingerprint_version', 'payload_sha256_plus_jsonb_args_md5_v1',
        'monotonic_guard_migration', '0027_house_roll_call_production_enablement'
    )
    WHERE id = v_result_roll_call_source_record_id
      AND source_system_key = 'house-clerk'
      AND source_record_key = v_roll_call_key
      AND record_type = 'legislative_roll_call';
    GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

    IF v_updated_rows <> 1 THEN
        RAISE EXCEPTION
            'House write confirmation row was not available for monotonic metadata'
            USING ERRCODE = '55000';
    END IF;

    RETURN QUERY SELECT
        v_result_roll_call_source_record_id,
        v_result_member_vote_count;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.upsert_house_roll_call(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_house_roll_call(jsonb, jsonb)
    TO service_role;

-- Preserve read-only health/preflight access while forcing every application
-- mutation through the reviewed security-definer RPCs.
REVOKE ALL PRIVILEGES ON TABLE
    public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes,
    public.source_catalog_sources,
    public.source_catalog_endpoints
FROM service_role;

GRANT SELECT ON TABLE
    public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes,
    public.source_catalog_sources,
    public.source_catalog_endpoints
TO service_role;

DO $privilege_closure$
DECLARE
    v_table text;
    v_column record;
    v_privilege text;
    v_tables text[] := ARRAY[
        'public.source_records',
        'public.legislative_roll_calls',
        'public.person_roll_call_votes',
        'public.source_catalog_sources',
        'public.source_catalog_endpoints'
    ];
BEGIN
    FOREACH v_table IN ARRAY v_tables LOOP
        IF has_table_privilege('service_role', v_table, 'SELECT') IS DISTINCT FROM true THEN
            RAISE EXCEPTION
                'service_role SELECT privilege closure failed for %',
                v_table
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
            IF has_table_privilege('service_role', v_table, v_privilege) THEN
                RAISE EXCEPTION
                    'service_role retains % privilege on %',
                    v_privilege,
                    v_table
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
              = ANY(v_tables)
        ORDER BY columns.table_schema, columns.table_name, columns.ordinal_position
    LOOP
        FOREACH v_privilege IN ARRAY ARRAY['INSERT', 'UPDATE', 'REFERENCES'] LOOP
            IF has_column_privilege(
                'service_role',
                v_column.qualified_table_name,
                v_column.column_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service_role retains column % privilege on %.%',
                    v_privilege,
                    v_column.qualified_table_name,
                    v_column.column_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;

    IF has_function_privilege(
        'service_role',
        'public.upsert_house_roll_call(jsonb,jsonb)',
        'EXECUTE'
    ) IS DISTINCT FROM true
       OR has_function_privilege(
            'service_role',
            'public.upsert_house_roll_call_0026(jsonb,jsonb)',
            'EXECUTE'
       )
       OR EXISTS (
            SELECT 1
            FROM pg_proc AS p
            CROSS JOIN LATERAL aclexplode(
                COALESCE(p.proacl, acldefault('f', p.proowner))
            ) AS acl
            WHERE p.oid = to_regprocedure(
                'public.upsert_house_roll_call_0026(jsonb,jsonb)'
            )
              AND acl.privilege_type = 'EXECUTE'
              AND acl.grantee <> p.proowner
       )
       OR EXISTS (
            SELECT 1
            FROM pg_proc AS p
            CROSS JOIN LATERAL aclexplode(
                COALESCE(p.proacl, acldefault('f', p.proowner))
            ) AS acl
            WHERE p.oid = to_regprocedure(
                'public.upsert_house_roll_call(jsonb,jsonb)'
            )
              AND acl.privilege_type = 'EXECUTE'
              AND acl.grantee NOT IN (
                  p.proowner,
                  'service_role'::regrole::oid
              )
       ) THEN
        RAISE EXCEPTION 'service_role House RPC privilege closure failed'
            USING ERRCODE = '42501';
    END IF;
END
$privilege_closure$;

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
        'monotonic_guard_migration', '0027_house_roll_call_production_enablement',
        'cutover_barrier_status', 'completed',
        'cutover_barrier_completed_at', clock_timestamp()
    )
    WHERE slug = 'house-clerk-roll-call-xml';
    GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

    IF v_updated_rows <> 1 THEN
        RAISE EXCEPTION 'House source gate enablement updated % rows, expected 1', v_updated_rows
            USING ERRCODE = '55000';
    END IF;

    UPDATE public.source_catalog_endpoints
    SET metadata = metadata || jsonb_build_object(
        'ingestion_status', 'production_enabled_monotonic',
        'production_write_status', 'production_enabled_monotonic',
        'production_writes_enabled', true,
        'runtime_write_status', 'runtime_opt_in_required',
        'monotonic_guard_migration', '0027_house_roll_call_production_enablement',
        'cutover_barrier_status', 'completed',
        'cutover_barrier_completed_at', clock_timestamp()
    )
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed';
    GET DIAGNOSTICS v_updated_rows = ROW_COUNT;

    IF v_updated_rows <> 1 THEN
        RAISE EXCEPTION 'House endpoint gate enablement updated % rows, expected 1', v_updated_rows
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
    '0027_house_roll_call_production_enablement',
    27,
    'Reject stale House roll-call observations and atomically enable the reviewed database write gates.',
    jsonb_build_object(
        'source_slug', 'house-clerk-roll-call-xml',
        'endpoint_slug', 'evs-roll-call-feed',
        'write_rpc', 'upsert_house_roll_call',
        'private_write_helper', 'upsert_house_roll_call_0026',
        'private_write_helper_body_md5', 'dbd0d605e017550c959157926400d395',
        'private_write_helper_reverse_dependencies_required', 0,
        'case_normalized_bioguide_unique', true,
        'monotonic_observations', true,
        'exact_replay_state_comparison', true,
        'exact_replay_controlled_metadata', true,
        'house_roll_call_source_record_contract', true,
        'service_role_direct_dml_revoked', jsonb_build_array(
            'source_records',
            'legislative_roll_calls',
            'person_roll_call_votes',
            'source_catalog_sources',
            'source_catalog_endpoints'
        ),
        'service_role_table_access', 'select_only_no_column_mutation',
        'strict_json_boolean_gates', true,
        'database_enforced_cutover_barrier', true,
        'cutover_barrier_body_md5', '684fd078d5d2149fe0950a0141cdd7b6',
        'pre_barrier_client_transactions_drained', true,
        'production_writes_enabled', true,
        'runtime_opt_in_required', true,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
