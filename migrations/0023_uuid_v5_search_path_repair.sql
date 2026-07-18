-- 0023_uuid_v5_search_path_repair.sql
--
-- Repair canonical-person creation after migration 0022. The legacy identity sync
-- function intentionally uses a restricted SECURITY DEFINER search_path, while
-- Supabase installs uuid-ossp in its dedicated extensions schema. Existing people
-- did not exercise uuid_generate_v5; the first new Congress member did.
--
-- This migration discovers the actual uuid-ossp schema, verifies that untrusted API
-- roles cannot create objects there, and adds only that schema to the function's
-- search_path. A private, non-mutating RPC makes the same resolution test part of
-- scraper preflight so another long ETL cannot hide this drift.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $$
DECLARE
    v_extension_schema name;
BEGIN
    SELECT namespace.nspname
    INTO v_extension_schema
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = extension.extnamespace
    WHERE extension.extname = 'uuid-ossp';

    IF v_extension_schema IS NULL THEN
        RAISE EXCEPTION 'uuid-ossp extension is required before applying migration 0023'
            USING ERRCODE = '42704';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_roles AS role
        WHERE role.rolname IN ('anon', 'authenticated')
          AND pg_catalog.has_schema_privilege(
              role.oid,
              v_extension_schema::text,
              'CREATE'
          )
    ) THEN
        RAISE EXCEPTION
            'uuid-ossp schema % is writable by an untrusted API role',
            v_extension_schema
            USING ERRCODE = '42501';
    END IF;

    EXECUTE pg_catalog.format(
        'ALTER FUNCTION public.sync_legacy_profile_identity(uuid) '
        'SET search_path = pg_catalog, %I',
        v_extension_schema
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.preflight_canonical_uuid_v5()
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_extension_schema name;
    v_expected_search_path text;
    v_generated uuid;
BEGIN
    SELECT namespace.nspname
    INTO v_extension_schema
    FROM pg_catalog.pg_extension AS extension
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = extension.extnamespace
    WHERE extension.extname = 'uuid-ossp';

    IF v_extension_schema IS NULL THEN
        RAISE EXCEPTION 'uuid-ossp extension is not installed' USING ERRCODE = '42704';
    END IF;

    v_expected_search_path := pg_catalog.format(
        'search_path=pg_catalog, %I',
        v_extension_schema
    );

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS proc
        WHERE proc.oid = pg_catalog.to_regprocedure(
            'public.sync_legacy_profile_identity(uuid)'
        )
          AND v_expected_search_path = ANY(
              COALESCE(proc.proconfig, ARRAY[]::text[])
          )
    ) THEN
        RAISE EXCEPTION
            'sync_legacy_profile_identity search_path cannot resolve uuid-ossp schema %',
            v_extension_schema
            USING ERRCODE = '42883';
    END IF;

    EXECUTE pg_catalog.format(
        'SELECT %I.uuid_generate_v5($1, $2)',
        v_extension_schema
    )
    INTO v_generated
    USING
        '6fb3f3e2-0f6f-42f4-b7e9-d8ed15ed8d2f'::uuid,
        'canonical-identity-preflight';

    IF v_generated IS NULL THEN
        RAISE EXCEPTION 'uuid_generate_v5 returned null' USING ERRCODE = '22004';
    END IF;

    RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.preflight_canonical_uuid_v5()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.preflight_canonical_uuid_v5()
    TO service_role;

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0023_uuid_v5_search_path_repair',
    23,
    'Repair UUID-v5 resolution for new canonical people and add a preflight probe.',
    jsonb_build_object(
        'repaired_function', 'public.sync_legacy_profile_identity(uuid)',
        'preflight_rpc', 'public.preflight_canonical_uuid_v5()'
    )
)
ON CONFLICT (migration_key) DO UPDATE SET
    description = EXCLUDED.description,
    metadata = public.schema_migrations.metadata || EXCLUDED.metadata;

NOTIFY pgrst, 'reload schema';

COMMIT;
