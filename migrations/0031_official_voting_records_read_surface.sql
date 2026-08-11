-- 0031_official_voting_records_read_surface.sql
--
-- Expose the already-normalized House and Senate roll-call facts through one
-- narrow, person-aware public read RPC. The provenance tables remain private;
-- callers receive only active, verified facts from the two reviewed official
-- sources plus the existing legacy vote rows needed for state and historical
-- compatibility.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0031_official_voting_records_read_surface'
    ) THEN
        RAISE EXCEPTION
            'migration 0031_official_voting_records_read_surface is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0030_senate_roll_call_production_enablement'
          AND migration_version = 30
    ) THEN
        RAISE EXCEPTION
            'migration 0030_senate_roll_call_production_enablement must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF to_regprocedure(
        'public.get_canonical_person_legacy_ids(uuid)'
    ) IS NULL THEN
        RAISE EXCEPTION
            'required canonical identity RPC is missing: get_canonical_person_legacy_ids(uuid)'
            USING ERRCODE = '42883';
    END IF;

    IF to_regclass('public.legislative_roll_calls') IS NULL
       OR to_regclass('public.person_roll_call_votes') IS NULL
       OR to_regclass('public.source_records') IS NULL THEN
        RAISE EXCEPTION
            'required private legislative provenance tables are missing'
            USING ERRCODE = '42P01';
    END IF;

    IF to_regprocedure(
        'public.get_canonical_voting_records_v2(uuid,integer,integer,text)'
    ) IS NOT NULL THEN
        RAISE EXCEPTION
            'get_canonical_voting_records_v2 already exists without the 0031 migration marker'
            USING ERRCODE = '55000';
    END IF;
END
$migration_preflight$;

CREATE FUNCTION public.get_canonical_voting_records_v2(
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $function$
    WITH canonical_legacy AS (
        SELECT DISTINCT
            resolved.person_id,
            resolved.legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id) AS resolved
    ),
    target_person AS (
        SELECT DISTINCT canonical_legacy.person_id
        FROM canonical_legacy
        JOIN public.people AS person
          ON person.id = canonical_legacy.person_id
         AND person.status = 'active'
    ),
    official_votes AS (
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
        FROM target_person
        JOIN public.person_roll_call_votes AS person_vote
          ON person_vote.person_id = target_person.person_id
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
        WHERE (
            roll_call.chamber = 'house'
            AND roll_call_source.source_system_key = 'house-clerk'
            AND roll_call_source.source_catalog_slug
                    = 'house-clerk-roll-call-xml'
            AND roll_call_source.source_endpoint_slug = 'evs-roll-call-feed'
            AND roll_call.canonical_roll_call_key ~ '^house:'
        ) OR (
            roll_call.chamber = 'senate'
            AND roll_call_source.source_system_key = 'senate-lis'
            AND roll_call_source.source_catalog_slug = 'senate-roll-call-xml'
            AND roll_call_source.source_endpoint_slug = 'lis-roll-call-feed'
            AND roll_call.canonical_roll_call_key ~ '^senate:'
        )
    ),
    legacy_spoke AS (
        SELECT legacy_vote.*
        FROM public.voting_records AS legacy_vote
        JOIN target_person
          ON target_person.person_id = legacy_vote.person_id

        UNION

        SELECT legacy_vote.*
        FROM public.voting_records AS legacy_vote
        JOIN canonical_legacy
          ON canonical_legacy.legacy_politician_id
                = legacy_vote.politician_id
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
    ),
    params AS (
        SELECT NULLIF(
            lower(
                replace(
                    btrim(coalesce(vote_cast_filter, '')),
                    ' ',
                    '_'
                )
            ),
            ''
        ) AS vote_cast_key
    )
    SELECT combined.*
    FROM combined
    CROSS JOIN params
    WHERE params.vote_cast_key IS NULL
       OR lower(replace(btrim(combined.vote_cast), ' ', '_'))
            = params.vote_cast_key
    ORDER BY
        combined.vote_date DESC,
        CASE combined.record_origin WHEN 'official' THEN 0 ELSE 1 END,
        combined.roll_call_id NULLS LAST,
        combined.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
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
    '0031_official_voting_records_read_surface',
    31,
    'Expose active verified House and Senate roll-call facts through a canonical person-aware profile RPC while retaining legacy non-duplicate coverage.',
    jsonb_build_object(
        'read_rpc', 'get_canonical_voting_records_v2',
        'official_sources', jsonb_build_array(
            'house-clerk-roll-call-xml',
            'senate-roll-call-xml'
        ),
        'private_fact_tables_remain_private', true,
        'legacy_compatibility', true,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
