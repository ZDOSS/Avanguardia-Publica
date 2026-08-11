-- 0032_official_voting_records_query_repair.sql
--
-- Repair the 0031 read plan before the profile UI ships. The SQL-language
-- implementation let the planner push the normalized vote-cast filter below
-- canonical-person joins, causing two full legacy voting_records scans. Resolve
-- the canonical person once in PL/pgSQL, constrain each branch by its indexed
-- person/profile key first, and then normalize the small matching row set.

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
        WHERE migration_key = '0032_official_voting_records_query_repair'
    ) THEN
        RAISE EXCEPTION
            'migration 0032_official_voting_records_query_repair is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0031_official_voting_records_read_surface'
          AND migration_version = 31
    ) THEN
        RAISE EXCEPTION
            'migration 0031_official_voting_records_read_surface must be applied first'
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
            'migration 0031 canonical voting-records v2 RPC is missing'
            USING ERRCODE = '42883';
    END IF;

    IF v_language IS DISTINCT FROM 'sql'
       OR v_security_definer IS DISTINCT FROM true
       OR v_volatility IS DISTINCT FROM 's'
       OR v_config IS DISTINCT FROM ARRAY['search_path=""']::text[]
       OR v_body_md5 IS DISTINCT FROM '67534a64b5bca1a74fbdbe7b511ff928' THEN
        RAISE EXCEPTION
            'migration 0031 RPC contract drifted before query repair: language %, security %, volatility %, config %, body %',
            v_language,
            v_security_definer,
            v_volatility,
            v_config,
            v_body_md5
            USING ERRCODE = '55000';
    END IF;

    IF NOT has_function_privilege(
        'anon',
        v_function_oid,
        'EXECUTE'
    ) OR NOT has_function_privilege(
        'authenticated',
        v_function_oid,
        'EXECUTE'
    ) OR EXISTS (
        SELECT 1
        FROM aclexplode(
            (SELECT proacl FROM pg_proc WHERE oid = v_function_oid)
        ) AS acl
        WHERE acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION
            'migration 0031 RPC execute privileges drifted before query repair'
            USING ERRCODE = '42501';
    END IF;
END
$migration_preflight$;

CREATE OR REPLACE FUNCTION public.get_canonical_voting_records_v2(
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
    source_updated_at timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
#variable_conflict use_column
DECLARE
    v_person_count integer;
    v_person_id uuid;
    v_legacy_politician_ids uuid[];
    v_person_is_active boolean;
    v_vote_cast_key text;
BEGIN
    SELECT
        count(DISTINCT resolved.person_id),
        (array_agg(
            DISTINCT resolved.person_id
            ORDER BY resolved.person_id
        ))[1],
        array_agg(
            DISTINCT resolved.legacy_politician_id
            ORDER BY resolved.legacy_politician_id
        )
    INTO
        v_person_count,
        v_person_id,
        v_legacy_politician_ids
    FROM public.get_canonical_person_legacy_ids(p_id) AS resolved;

    IF v_person_count = 0 THEN
        RETURN;
    END IF;

    IF v_person_count <> 1 THEN
        RAISE EXCEPTION
            'canonical voting-record resolution returned % people for one profile',
            v_person_count
            USING ERRCODE = '21000';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.people AS person
        WHERE person.id = v_person_id
          AND person.status = 'active'
    )
    INTO v_person_is_active;

    v_vote_cast_key := NULLIF(
        lower(
            replace(
                btrim(coalesce(vote_cast_filter, '')),
                ' ',
                '_'
            )
        ),
        ''
    );

    RETURN QUERY
    WITH official_votes AS (
        SELECT
            person_vote.source_record_id AS id,
            roll_call.question AS bill_name,
            NULL::text AS bill_summary,
            roll_call.vote_date,
            CASE person_vote.vote_cast
                WHEN 'yea' THEN 'Yea'
                WHEN 'nay' THEN 'Nay'
                WHEN 'present' THEN 'Present'
                WHEN 'not_voting' THEN 'Not Voting'
            END AS vote_cast,
            'United States'::text AS jurisdiction,
            roll_call.canonical_roll_call_key AS roll_call_id,
            'official'::text AS record_origin,
            roll_call.chamber,
            roll_call.congress,
            roll_call.session,
            roll_call.roll_call_number,
            roll_call.vote_result,
            source_system.display_name AS source_name,
            roll_call_source.source_url,
            GREATEST(
                roll_call_source.last_seen_at,
                person_vote_source.last_seen_at
            ) AS source_updated_at
        FROM public.person_roll_call_votes AS person_vote
        JOIN public.source_records AS person_vote_source
          ON person_vote_source.id = person_vote.source_record_id
         AND person_vote_source.person_id = person_vote.person_id
         AND person_vote_source.record_type = 'person_roll_call_vote'
         AND person_vote_source.record_status = 'active'
         AND person_vote_source.retired_at IS NULL
         AND person_vote_source.verified_lane = 'verified'
        JOIN public.legislative_roll_calls AS roll_call
          ON roll_call.source_record_id = person_vote.roll_call_source_record_id
        JOIN public.source_records AS roll_call_source
          ON roll_call_source.id = roll_call.source_record_id
         AND roll_call_source.record_type = 'legislative_roll_call'
         AND roll_call_source.record_status = 'active'
         AND roll_call_source.retired_at IS NULL
         AND roll_call_source.verified_lane = 'verified'
         AND roll_call_source.person_id IS NULL
         AND roll_call_source.source_system_key
                = person_vote_source.source_system_key
         AND roll_call_source.source_catalog_slug
                = person_vote_source.source_catalog_slug
         AND roll_call_source.source_endpoint_slug
                = person_vote_source.source_endpoint_slug
         AND roll_call_source.source_url = person_vote_source.source_url
        JOIN public.source_systems AS source_system
          ON source_system.key = roll_call_source.source_system_key
         AND source_system.source_kind = 'government'
         AND source_system.trust_level = 'official'
         AND source_system.verified = true
        JOIN public.source_catalog_sources AS catalog_source
          ON catalog_source.slug = roll_call_source.source_catalog_slug
         AND catalog_source.status = 'approved'
         AND catalog_source.repo_fit = 'wired'
         AND catalog_source.verified_lane = 'verified'
        JOIN public.source_catalog_endpoints AS catalog_endpoint
          ON catalog_endpoint.source_slug = roll_call_source.source_catalog_slug
         AND catalog_endpoint.endpoint_slug
                = roll_call_source.source_endpoint_slug
         AND catalog_endpoint.status = 'approved'
        WHERE v_person_is_active
          AND person_vote.person_id = v_person_id
          AND (
              v_vote_cast_key IS NULL
              OR person_vote.vote_cast = v_vote_cast_key
          )
          AND (
              (
                  roll_call.chamber = 'house'
                  AND roll_call_source.source_system_key = 'house-clerk'
                  AND roll_call_source.source_catalog_slug
                        = 'house-clerk-roll-call-xml'
                  AND roll_call_source.source_endpoint_slug
                        = 'evs-roll-call-feed'
                  AND roll_call.canonical_roll_call_key ~ '^house:'
              ) OR (
                  roll_call.chamber = 'senate'
                  AND roll_call_source.source_system_key = 'senate-lis'
                  AND roll_call_source.source_catalog_slug
                        = 'senate-roll-call-xml'
                  AND roll_call_source.source_endpoint_slug
                        = 'lis-roll-call-feed'
                  AND roll_call.canonical_roll_call_key ~ '^senate:'
              )
          )
    ),
    legacy_spoke AS (
        SELECT legacy_vote.*
        FROM public.voting_records AS legacy_vote
        WHERE v_person_is_active
          AND legacy_vote.person_id = v_person_id
          AND (
              v_vote_cast_key IS NULL
              OR CASE lower(btrim(coalesce(legacy_vote.vote_cast, '')))
                  WHEN 'aye' THEN 'yea'
                  WHEN 'yes' THEN 'yea'
                  WHEN 'yea' THEN 'yea'
                  WHEN 'nay' THEN 'nay'
                  WHEN 'no' THEN 'nay'
                  WHEN 'present' THEN 'present'
                  WHEN 'not voting' THEN 'not_voting'
                  WHEN 'not_voting' THEN 'not_voting'
                  ELSE lower(
                      replace(
                          btrim(coalesce(legacy_vote.vote_cast, '')),
                          ' ',
                          '_'
                      )
                  )
              END = v_vote_cast_key
          )

        UNION

        SELECT legacy_vote.*
        FROM public.voting_records AS legacy_vote
        WHERE legacy_vote.politician_id = ANY(v_legacy_politician_ids)
          AND (
              v_vote_cast_key IS NULL
              OR CASE lower(btrim(coalesce(legacy_vote.vote_cast, '')))
                  WHEN 'aye' THEN 'yea'
                  WHEN 'yes' THEN 'yea'
                  WHEN 'yea' THEN 'yea'
                  WHEN 'nay' THEN 'nay'
                  WHEN 'no' THEN 'nay'
                  WHEN 'present' THEN 'present'
                  WHEN 'not voting' THEN 'not_voting'
                  WHEN 'not_voting' THEN 'not_voting'
                  ELSE lower(
                      replace(
                          btrim(coalesce(legacy_vote.vote_cast, '')),
                          ' ',
                          '_'
                      )
                  )
              END = v_vote_cast_key
          )
    ),
    legacy_votes AS (
        SELECT
            legacy_vote.id,
            legacy_vote.bill_name,
            legacy_vote.bill_summary,
            legacy_vote.vote_date,
            CASE lower(btrim(coalesce(legacy_vote.vote_cast, '')))
                WHEN 'aye' THEN 'Yea'
                WHEN 'yes' THEN 'Yea'
                WHEN 'yea' THEN 'Yea'
                WHEN 'nay' THEN 'Nay'
                WHEN 'no' THEN 'Nay'
                WHEN 'present' THEN 'Present'
                WHEN 'not voting' THEN 'Not Voting'
                WHEN 'not_voting' THEN 'Not Voting'
                ELSE legacy_vote.vote_cast
            END AS vote_cast,
            legacy_vote.jurisdiction,
            legacy_vote.roll_call_id,
            'legacy'::text AS record_origin,
            NULL::text AS chamber,
            NULL::integer AS congress,
            NULL::smallint AS session,
            NULL::integer AS roll_call_number,
            NULL::text AS vote_result,
            CASE
                WHEN legacy_vote.roll_call_id LIKE 'govtrack:%' THEN 'GovTrack'
                WHEN legacy_vote.roll_call_id LIKE 'openstates:%' THEN 'OpenStates'
            END AS source_name,
            NULL::text AS source_url,
            NULL::timestamptz AS source_updated_at
        FROM legacy_spoke AS legacy_vote
        WHERE NOT EXISTS (
            SELECT 1
            FROM official_votes AS official_vote
            WHERE official_vote.vote_date = legacy_vote.vote_date
              AND (
                  official_vote.roll_call_id = legacy_vote.roll_call_id
                  OR legacy_vote.roll_call_id LIKE 'govtrack:%'
              )
              AND lower(
                  regexp_replace(
                      btrim(official_vote.bill_name),
                      '\s+',
                      ' ',
                      'g'
                  )
              ) = lower(
                  regexp_replace(
                      btrim(legacy_vote.bill_name),
                      '\s+',
                      ' ',
                      'g'
                  )
              )
              AND lower(
                  replace(
                      btrim(official_vote.vote_cast),
                      ' ',
                      '_'
                  )
              ) = CASE lower(btrim(coalesce(legacy_vote.vote_cast, '')))
                  WHEN 'aye' THEN 'yea'
                  WHEN 'yes' THEN 'yea'
                  WHEN 'yea' THEN 'yea'
                  WHEN 'nay' THEN 'nay'
                  WHEN 'no' THEN 'nay'
                  WHEN 'present' THEN 'present'
                  WHEN 'not voting' THEN 'not_voting'
                  WHEN 'not_voting' THEN 'not_voting'
                  ELSE lower(
                      replace(
                          btrim(coalesce(legacy_vote.vote_cast, '')),
                          ' ',
                          '_'
                      )
                  )
              END
        )
    ),
    combined AS (
        SELECT * FROM official_votes
        UNION ALL
        SELECT * FROM legacy_votes
    )
    SELECT combined.*
    FROM combined
    ORDER BY
        combined.vote_date DESC,
        CASE combined.record_origin WHEN 'official' THEN 0 ELSE 1 END,
        combined.roll_call_id NULLS LAST,
        combined.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v2(
    uuid,
    integer,
    integer,
    text
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_voting_records_v2(
    uuid,
    integer,
    integer,
    text
) TO anon, authenticated;

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0032_official_voting_records_query_repair',
    32,
    'Repair the official-vote profile RPC so person constraints and vote filters stay on indexed per-profile branches.',
    jsonb_build_object(
        'read_rpc', 'get_canonical_voting_records_v2',
        'replaces_migration', '0031_official_voting_records_read_surface',
        'prior_function_body_md5', '67534a64b5bca1a74fbdbe7b511ff928',
        'planner_repair', 'resolve_person_once_and_filter_indexed_branches',
        'private_fact_tables_remain_private', true,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
