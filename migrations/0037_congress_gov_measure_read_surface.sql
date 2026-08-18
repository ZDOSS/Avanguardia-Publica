-- 0037_congress_gov_measure_read_surface.sql
--
-- Expose the already-reviewed Congress.gov bill/amendment facts through one
-- narrow versioned profile RPC. The proven v2 voting-record RPC remains the
-- authority for person resolution, official/legacy coverage, deduplication,
-- filtering, ordering, and pagination. This wrapper only decorates each
-- returned official roll call with a bounded array of exact linked measures.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
DECLARE
    v_function_oid oid;
    v_language text;
    v_security_definer boolean;
    v_volatility "char";
    v_config text[];
    v_body_md5 text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0037_congress_gov_measure_read_surface'
    ) THEN
        RAISE EXCEPTION
            'migration 0037_congress_gov_measure_read_surface is already recorded; do not replay forward-only migrations'
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

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0036_congress_gov_scheduled_enablement'
          AND migration_version = 36
    ) THEN
        RAISE EXCEPTION
            'migration 0036_congress_gov_scheduled_enablement must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF to_regprocedure(
        'public.get_canonical_voting_records_v3(uuid,integer,integer,text)'
    ) IS NOT NULL THEN
        RAISE EXCEPTION
            'get_canonical_voting_records_v3 already exists without the 0037 migration marker'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        function_state.oid,
        language_state.lanname,
        function_state.prosecdef,
        function_state.provolatile,
        function_state.proconfig,
        md5(function_state.prosrc)
    INTO
        v_function_oid,
        v_language,
        v_security_definer,
        v_volatility,
        v_config,
        v_body_md5
    FROM pg_proc AS function_state
    JOIN pg_language AS language_state
      ON language_state.oid = function_state.prolang
    WHERE function_state.oid = to_regprocedure(
        'public.get_canonical_voting_records_v2(uuid,integer,integer,text)'
    );

    IF v_function_oid IS NULL THEN
        RAISE EXCEPTION
            'migration 0033 canonical voting-records v2 RPC is missing'
            USING ERRCODE = '42883';
    END IF;

    IF v_language IS DISTINCT FROM 'plpgsql'
       OR v_security_definer IS DISTINCT FROM true
       OR v_volatility IS DISTINCT FROM 's'
       OR v_config IS DISTINCT FROM ARRAY['search_path=""']::text[]
       OR v_body_md5 IS DISTINCT FROM '29cee3603f567c2429947232d0279eff' THEN
        RAISE EXCEPTION
            'migration 0033 RPC contract drifted before measure presentation: language %, security %, volatility %, config %, body %',
            v_language,
            v_security_definer,
            v_volatility,
            v_config,
            v_body_md5
            USING ERRCODE = '55000';
    END IF;

    IF NOT has_function_privilege('anon', v_function_oid, 'EXECUTE')
       OR NOT has_function_privilege('authenticated', v_function_oid, 'EXECUTE')
       OR EXISTS (
            SELECT 1
            FROM aclexplode(
                (SELECT proacl FROM pg_proc WHERE oid = v_function_oid)
            ) AS acl
            WHERE acl.grantee = 0
              AND acl.privilege_type = 'EXECUTE'
       ) THEN
        RAISE EXCEPTION
            'migration 0033 RPC execute privileges drifted before measure presentation'
            USING ERRCODE = '42501';
    END IF;

    IF to_regclass('public.legislative_roll_calls') IS NULL
       OR to_regclass('public.legislative_measures') IS NULL
       OR to_regclass('public.legislative_roll_call_measure_links') IS NULL
       OR to_regclass('public.source_records') IS NULL THEN
        RAISE EXCEPTION
            'Congress.gov measure or official roll-call fact tables are missing'
            USING ERRCODE = '42P01';
    END IF;

    IF has_table_privilege('anon', 'public.source_records', 'SELECT')
       OR has_table_privilege('authenticated', 'public.source_records', 'SELECT')
       OR has_table_privilege('anon', 'public.legislative_roll_calls', 'SELECT')
       OR has_table_privilege('authenticated', 'public.legislative_roll_calls', 'SELECT')
       OR has_table_privilege('anon', 'public.legislative_measures', 'SELECT')
       OR has_table_privilege('authenticated', 'public.legislative_measures', 'SELECT')
       OR has_table_privilege(
            'anon',
            'public.legislative_roll_call_measure_links',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_roll_call_measure_links',
            'SELECT'
       ) THEN
        RAISE EXCEPTION
            'private provenance or legislative fact tables are readable by browser roles'
            USING ERRCODE = '42501';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.source_systems AS source_system
        JOIN public.source_catalog_source_system_links AS catalog_link
          ON catalog_link.source_system_key = source_system.key
        JOIN public.source_catalog_sources AS catalog_source
          ON catalog_source.slug = catalog_link.source_slug
        JOIN public.source_catalog_endpoints AS catalog_endpoint
          ON catalog_endpoint.source_slug = catalog_source.slug
        WHERE source_system.key = 'congress-gov'
          AND source_system.source_kind = 'government'
          AND source_system.trust_level = 'official'
          AND source_system.verified = true
          AND catalog_link.link_type = 'same_source'
          AND catalog_source.slug = 'congress-gov-api'
          AND catalog_source.status = 'approved'
          AND catalog_source.repo_fit = 'wired'
          AND catalog_source.verified_lane = 'verified'
          AND catalog_endpoint.endpoint_slug = 'api-v3'
          AND catalog_endpoint.status = 'approved'
    ) THEN
        RAISE EXCEPTION
            'reviewed Congress.gov source and endpoint contract is unavailable'
            USING ERRCODE = '55000';
    END IF;
END
$migration_preflight$;

CREATE FUNCTION public.get_canonical_voting_records_v3(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0,
    vote_cast_filter text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    bill_name text,
    bill_summary text,
    vote_date date,
    vote_cast text,
    jurisdiction text,
    roll_call_id text,
    record_origin text,
    chamber text,
    congress integer,
    session smallint,
    roll_call_number integer,
    vote_result text,
    source_name text,
    source_url text,
    source_updated_at timestamptz,
    measures jsonb
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    SELECT
        vote.id,
        vote.bill_name,
        vote.bill_summary,
        vote.vote_date,
        vote.vote_cast,
        vote.jurisdiction,
        vote.roll_call_id,
        vote.record_origin,
        vote.chamber,
        vote.congress,
        vote.session,
        vote.roll_call_number,
        vote.vote_result,
        vote.source_name,
        vote.source_url,
        vote.source_updated_at,
        CASE
            WHEN vote.record_origin = 'official'
                THEN COALESCE(measure_set.measures, '[]'::jsonb)
            ELSE '[]'::jsonb
        END AS measures
    FROM public.get_canonical_voting_records_v2(
        p_id,
        result_limit,
        result_offset,
        vote_cast_filter
    ) AS vote
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(
            bounded_measure.presentation
            ORDER BY
                bounded_measure.measure_kind,
                bounded_measure.measure_type,
                bounded_measure.measure_number,
                bounded_measure.canonical_measure_key
        ) AS measures
        FROM (
            SELECT
                measure.measure_kind,
                measure.measure_type,
                measure.measure_number,
                measure.canonical_measure_key,
                jsonb_build_object(
                    'canonical_measure_key', measure.canonical_measure_key,
                    'measure_kind', measure.measure_kind,
                    'congress', measure.congress,
                    'measure_type', measure.measure_type,
                    'measure_number', measure.measure_number,
                    'title', CASE
                        WHEN char_length(measure.title) > 1000
                            THEN left(measure.title, 999) || '…'
                        ELSE measure.title
                    END,
                    'purpose', CASE
                        WHEN char_length(measure.purpose) > 2000
                            THEN left(measure.purpose, 1999) || '…'
                        ELSE measure.purpose
                    END,
                    'official_url', CASE
                        WHEN measure.official_url LIKE 'https://www.congress.gov/%'
                            THEN measure.official_url
                        ELSE NULL
                    END,
                    'source_name', measure_source_system.display_name,
                    'observed_at', measure_source.last_seen_at
                ) AS presentation
            FROM public.legislative_roll_calls AS roll_call
            JOIN public.source_records AS roll_call_source
              ON roll_call_source.id = roll_call.source_record_id
             AND roll_call_source.record_type = 'legislative_roll_call'
             AND roll_call_source.person_id IS NULL
             AND roll_call_source.legacy_politician_id IS NULL
             AND roll_call_source.verified_lane = 'verified'
             AND roll_call_source.record_status = 'active'
             AND roll_call_source.retired_at IS NULL
             AND roll_call_source.source_url = vote.source_url
             AND (
                  (
                      vote.chamber = 'house'
                      AND roll_call_source.source_system_key = 'house-clerk'
                      AND roll_call_source.source_catalog_slug =
                            'house-clerk-roll-call-xml'
                      AND roll_call_source.source_endpoint_slug =
                            'evs-roll-call-feed'
                  )
                  OR
                  (
                      vote.chamber = 'senate'
                      AND roll_call_source.source_system_key = 'senate-lis'
                      AND roll_call_source.source_catalog_slug =
                            'senate-roll-call-xml'
                      AND roll_call_source.source_endpoint_slug =
                            'lis-roll-call-feed'
                  )
             )
            JOIN public.legislative_roll_call_measure_links AS measure_link
              ON measure_link.roll_call_source_record_id = roll_call.source_record_id
             AND measure_link.link_basis = 'exact_official_measure_identifier'
            JOIN public.legislative_measures AS measure
              ON measure.source_record_id = measure_link.measure_source_record_id
             AND measure.congress = roll_call.congress
            JOIN public.source_records AS measure_source
              ON measure_source.id = measure.source_record_id
             AND measure_source.source_system_key = 'congress-gov'
             AND measure_source.source_record_key = measure.canonical_measure_key
             AND measure_source.record_type = 'legislative_measure'
             AND measure_source.person_id IS NULL
             AND measure_source.legacy_politician_id IS NULL
             AND measure_source.source_catalog_slug = 'congress-gov-api'
             AND measure_source.source_endpoint_slug = 'api-v3'
             AND measure_source.source_url = format(
                    'https://api.congress.gov/v3/%s/%s/%s/%s',
                    measure.measure_kind,
                    measure.congress,
                    measure.measure_type,
                    measure.measure_number
                 )
             AND measure_source.verified_lane = 'verified'
             AND measure_source.record_status = 'active'
             AND measure_source.retired_at IS NULL
            JOIN public.source_systems AS measure_source_system
              ON measure_source_system.key = measure_source.source_system_key
             AND measure_source_system.source_kind = 'government'
             AND measure_source_system.trust_level = 'official'
             AND measure_source_system.verified = true
            JOIN public.source_catalog_sources AS measure_catalog_source
              ON measure_catalog_source.slug = measure_source.source_catalog_slug
             AND measure_catalog_source.status = 'approved'
             AND measure_catalog_source.repo_fit = 'wired'
             AND measure_catalog_source.verified_lane = 'verified'
            JOIN public.source_catalog_source_system_links AS measure_catalog_link
              ON measure_catalog_link.source_slug = measure_catalog_source.slug
             AND measure_catalog_link.source_system_key =
                    measure_source.source_system_key
             AND measure_catalog_link.link_type = 'same_source'
            JOIN public.source_catalog_endpoints AS measure_catalog_endpoint
              ON measure_catalog_endpoint.source_slug =
                    measure_source.source_catalog_slug
             AND measure_catalog_endpoint.endpoint_slug =
                    measure_source.source_endpoint_slug
             AND measure_catalog_endpoint.status = 'approved'
            WHERE vote.record_origin = 'official'
              AND roll_call.canonical_roll_call_key = vote.roll_call_id
            ORDER BY
                measure.measure_kind,
                measure.measure_type,
                measure.measure_number,
                measure.canonical_measure_key
            LIMIT 100
        ) AS bounded_measure
    ) AS measure_set ON vote.record_origin = 'official'
    ORDER BY
        vote.vote_date DESC,
        CASE vote.record_origin WHEN 'official' THEN 0 ELSE 1 END,
        vote.roll_call_id NULLS LAST,
        vote.id;
$function$;

REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v3(
    uuid,
    integer,
    integer,
    text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_voting_records_v3(
    uuid,
    integer,
    integer,
    text
) TO anon, authenticated;

DO $migration_postconditions$
DECLARE
    v_function_oid oid;
BEGIN
    v_function_oid := to_regprocedure(
        'public.get_canonical_voting_records_v3(uuid,integer,integer,text)'
    );

    IF v_function_oid IS NULL
       OR NOT (
            SELECT function_state.prosecdef
            FROM pg_proc AS function_state
            WHERE function_state.oid = v_function_oid
       )
       OR NOT has_function_privilege('anon', v_function_oid, 'EXECUTE')
       OR NOT has_function_privilege('authenticated', v_function_oid, 'EXECUTE')
       OR EXISTS (
            SELECT 1
            FROM aclexplode(
                (SELECT proacl FROM pg_proc WHERE oid = v_function_oid)
            ) AS acl
            WHERE acl.grantee = 0
              AND acl.privilege_type = 'EXECUTE'
       ) THEN
        RAISE EXCEPTION
            'measure-aware voting-record RPC security contract was not installed'
            USING ERRCODE = '42501';
    END IF;

    IF has_table_privilege('anon', 'public.source_records', 'SELECT')
       OR has_table_privilege('authenticated', 'public.source_records', 'SELECT')
       OR has_table_privilege('anon', 'public.legislative_roll_calls', 'SELECT')
       OR has_table_privilege(
            'authenticated',
            'public.legislative_roll_calls',
            'SELECT'
       )
       OR has_table_privilege('anon', 'public.legislative_measures', 'SELECT')
       OR has_table_privilege('authenticated', 'public.legislative_measures', 'SELECT')
       OR has_table_privilege(
            'anon',
            'public.legislative_roll_call_measure_links',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_roll_call_measure_links',
            'SELECT'
       ) THEN
        RAISE EXCEPTION
            'measure read surface opened a private table to browser roles'
            USING ERRCODE = '42501';
    END IF;
END
$migration_postconditions$;

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0037_congress_gov_measure_read_surface',
    37,
    'Expose bounded presentation-safe Congress.gov measure metadata through a versioned canonical voting-record RPC.',
    jsonb_build_object(
        'read_rpc', 'get_canonical_voting_records_v3',
        'delegates_vote_contract_to', 'get_canonical_voting_records_v2',
        'measure_source', 'congress-gov-api',
        'measure_endpoint', 'api-v3',
        'join_policy', 'exact_official_roll_call_measure_identifier_only',
        'maximum_measures_per_returned_vote', 100,
        'maximum_title_characters', 1000,
        'maximum_purpose_characters', 2000,
        'presentation_fields', jsonb_build_array(
            'canonical_measure_key',
            'measure_kind',
            'congress',
            'measure_type',
            'measure_number',
            'title',
            'purpose',
            'official_url',
            'source_name',
            'observed_at'
        ),
        'raw_json_exposed', false,
        'direct_private_table_access_created', false,
        'legacy_vote_contract_changed', false,
        'scraper_write_contract_changed', false,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
