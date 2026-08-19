-- 0038_canonical_federal_voting_analytics.sql
--
-- Turn the reviewed private House/Senate roll-call facts into one inspectable,
-- canonical-person analytics feature. The internal read model remains closed to
-- every browser and service role. Three bounded SECURITY DEFINER RPCs expose only:
--
--   * per-person coverage and participation summaries by chamber/Congress;
--   * same-scope Yea/Nay alignment rankings with a ten-vote minimum sample; and
--   * paginated pairwise Yea/Nay evidence with exact official source links and
--     presentation-safe Congress.gov measure metadata.
--
-- Present and Not Voting remain visible in the participation summary but never
-- enter the alignment denominator. Legacy voting_records are deliberately absent:
-- state and historical coverage stays a separate presentation lane.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0038_canonical_federal_voting_analytics'
    ) THEN
        RAISE EXCEPTION
            'migration 0038_canonical_federal_voting_analytics is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0037_congress_gov_measure_read_surface'
          AND migration_version = 37
    ) THEN
        RAISE EXCEPTION
            'migration 0037_congress_gov_measure_read_surface must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF to_regclass(
        'public.canonical_verified_federal_roll_call_votes_v1'
    ) IS NOT NULL
       OR to_regprocedure(
            'public.get_canonical_federal_voting_summary_v1(uuid)'
       ) IS NOT NULL
       OR to_regprocedure(
            'public.get_canonical_federal_voting_alignment_v1(uuid,text,integer,integer)'
       ) IS NOT NULL
       OR to_regprocedure(
            'public.get_canonical_federal_voting_comparison_v1(uuid,uuid,text,integer,text,integer,integer)'
       ) IS NOT NULL THEN
        RAISE EXCEPTION
            'one or more 0038 voting analytics objects already exist without the migration marker'
            USING ERRCODE = '55000';
    END IF;

    IF to_regprocedure(
        'public.get_canonical_person_legacy_ids(uuid)'
    ) IS NULL
       OR to_regprocedure(
            'public.get_canonical_politician_header(uuid)'
       ) IS NULL THEN
        RAISE EXCEPTION
            'canonical identity/header RPCs are missing'
            USING ERRCODE = '42883';
    END IF;

    IF to_regclass('public.people') IS NULL
       OR to_regclass('public.source_records') IS NULL
       OR to_regclass('public.legislative_roll_calls') IS NULL
       OR to_regclass('public.person_roll_call_votes') IS NULL
       OR to_regclass('public.legislative_measures') IS NULL
       OR to_regclass(
            'public.legislative_roll_call_measure_links'
       ) IS NULL THEN
        RAISE EXCEPTION
            'canonical identity or legislative fact tables are missing'
            USING ERRCODE = '42P01';
    END IF;

    IF has_table_privilege('anon', 'public.source_records', 'SELECT')
       OR has_table_privilege('authenticated', 'public.source_records', 'SELECT')
       OR has_table_privilege(
            'anon',
            'public.legislative_roll_calls',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_roll_calls',
            'SELECT'
       )
       OR has_table_privilege(
            'anon',
            'public.person_roll_call_votes',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.person_roll_call_votes',
            'SELECT'
       )
       OR has_table_privilege(
            'anon',
            'public.legislative_measures',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_measures',
            'SELECT'
       )
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
            'private legislative facts are unexpectedly readable before analytics rollout'
            USING ERRCODE = '42501';
    END IF;
END
$migration_preflight$;

-- This view is an owner-only contract shared by the three public RPCs. It keeps
-- source verification identical across summary, ranking, and evidence queries.
-- security_invoker means an accidental future view grant still cannot bypass the
-- underlying table ACLs; the SECURITY DEFINER RPC owner is the intended reader. Do
-- not add security_barrier here: these predicates contain no caller-controlled
-- functions, and indexed person/scope filters must be eligible for pushdown.
CREATE VIEW public.canonical_verified_federal_roll_call_votes_v1
WITH (security_invoker = true)
AS
SELECT
    person_vote.source_record_id AS person_vote_source_record_id,
    person_vote.roll_call_source_record_id,
    person_vote.person_id,
    person_vote.vote_cast,
    roll_call.canonical_roll_call_key,
    roll_call.chamber,
    roll_call.congress,
    roll_call.session,
    roll_call.roll_call_number,
    roll_call.vote_date,
    roll_call.question,
    roll_call.vote_result,
    source_system.display_name AS source_name,
    roll_call_source.source_system_key,
    roll_call_source.source_catalog_slug,
    roll_call_source.source_endpoint_slug,
    roll_call_source.source_url,
    GREATEST(
        roll_call_source.last_seen_at,
        person_vote_source.last_seen_at
    ) AS source_updated_at
FROM public.person_roll_call_votes AS person_vote
JOIN public.people AS person
  ON person.id = person_vote.person_id
 AND person.status = 'active'
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
 AND roll_call_source.source_system_key = person_vote_source.source_system_key
 AND roll_call_source.source_catalog_slug = person_vote_source.source_catalog_slug
 AND roll_call_source.source_endpoint_slug = person_vote_source.source_endpoint_slug
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
 AND catalog_endpoint.endpoint_slug = roll_call_source.source_endpoint_slug
 AND catalog_endpoint.status = 'approved'
WHERE (
    roll_call.chamber = 'house'
    AND roll_call_source.source_system_key = 'house-clerk'
    AND roll_call_source.source_catalog_slug = 'house-clerk-roll-call-xml'
    AND roll_call_source.source_endpoint_slug = 'evs-roll-call-feed'
    AND roll_call.canonical_roll_call_key ~ '^house:'
) OR (
    roll_call.chamber = 'senate'
    AND roll_call_source.source_system_key = 'senate-lis'
    AND roll_call_source.source_catalog_slug = 'senate-roll-call-xml'
    AND roll_call_source.source_endpoint_slug = 'lis-roll-call-feed'
    AND roll_call.canonical_roll_call_key ~ '^senate:'
);

REVOKE ALL ON TABLE public.canonical_verified_federal_roll_call_votes_v1
    FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION public.get_canonical_federal_voting_summary_v1(p_id uuid)
RETURNS TABLE (
    person_id uuid,
    chamber text,
    congress integer,
    first_vote_date date,
    last_vote_date date,
    covered_vote_count bigint,
    participating_vote_count bigint,
    substantive_vote_count bigint,
    yea_count bigint,
    nay_count bigint,
    present_count bigint,
    not_voting_count bigint,
    participation_rate numeric,
    alignment_minimum_shared_votes integer,
    source_name text,
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
    v_person_is_active boolean;
BEGIN
    SELECT
        count(DISTINCT resolved.person_id),
        (array_agg(
            DISTINCT resolved.person_id
            ORDER BY resolved.person_id
        ))[1]
    INTO v_person_count, v_person_id
    FROM public.get_canonical_person_legacy_ids(p_id) AS resolved;

    IF v_person_count = 0 THEN
        RETURN;
    END IF;

    IF v_person_count <> 1 THEN
        RAISE EXCEPTION
            'canonical voting-summary resolution returned % people for one profile',
            v_person_count
            USING ERRCODE = '21000';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.people AS person
        WHERE person.id = v_person_id
          AND person.status = 'active'
    ) INTO v_person_is_active;

    IF NOT v_person_is_active THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        v_person_id,
        vote.chamber,
        vote.congress,
        min(vote.vote_date),
        max(vote.vote_date),
        count(*),
        count(*) FILTER (WHERE vote.vote_cast <> 'not_voting'),
        count(*) FILTER (WHERE vote.vote_cast IN ('yea', 'nay')),
        count(*) FILTER (WHERE vote.vote_cast = 'yea'),
        count(*) FILTER (WHERE vote.vote_cast = 'nay'),
        count(*) FILTER (WHERE vote.vote_cast = 'present'),
        count(*) FILTER (WHERE vote.vote_cast = 'not_voting'),
        round(
            count(*) FILTER (
                WHERE vote.vote_cast <> 'not_voting'
            )::numeric / NULLIF(count(*), 0),
            3
        ),
        10,
        max(vote.source_name),
        max(vote.source_updated_at)
    FROM public.canonical_verified_federal_roll_call_votes_v1 AS vote
    WHERE vote.person_id = v_person_id
    GROUP BY vote.chamber, vote.congress
    ORDER BY
        max(vote.vote_date) DESC,
        vote.congress DESC,
        vote.chamber
    LIMIT 20;
END
$function$;

CREATE FUNCTION public.get_canonical_federal_voting_alignment_v1(
    p_id uuid,
    scope_chamber text DEFAULT NULL,
    scope_congress integer DEFAULT NULL,
    result_limit_per_side integer DEFAULT 6
)
RETURNS TABLE (
    peer_person_id uuid,
    full_name text,
    current_office text,
    party text,
    state text,
    district text,
    chamber text,
    congress integer,
    agree_count bigint,
    differ_count bigint,
    shared_substantive_count bigint,
    agreement_rate numeric,
    first_shared_vote_date date,
    last_shared_vote_date date,
    aligned_rank bigint,
    differing_rank bigint,
    source_name text,
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
    v_person_is_active boolean;
    v_chamber text;
    v_congress integer;
    v_limit integer;
BEGIN
    SELECT
        count(DISTINCT resolved.person_id),
        (array_agg(
            DISTINCT resolved.person_id
            ORDER BY resolved.person_id
        ))[1]
    INTO v_person_count, v_person_id
    FROM public.get_canonical_person_legacy_ids(p_id) AS resolved;

    IF v_person_count = 0 THEN
        RETURN;
    END IF;

    IF v_person_count <> 1 THEN
        RAISE EXCEPTION
            'canonical voting-alignment resolution returned % people for one profile',
            v_person_count
            USING ERRCODE = '21000';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.people AS person
        WHERE person.id = v_person_id
          AND person.status = 'active'
    ) INTO v_person_is_active;

    IF NOT v_person_is_active THEN
        RETURN;
    END IF;

    IF (NULLIF(btrim(scope_chamber), '') IS NULL)
       IS DISTINCT FROM (scope_congress IS NULL) THEN
        RAISE EXCEPTION
            'scope_chamber and scope_congress must be supplied together'
            USING ERRCODE = '22023';
    END IF;

    IF scope_chamber IS NULL THEN
        SELECT vote.chamber, vote.congress
        INTO v_chamber, v_congress
        FROM public.canonical_verified_federal_roll_call_votes_v1 AS vote
        WHERE vote.person_id = v_person_id
        GROUP BY vote.chamber, vote.congress
        ORDER BY max(vote.vote_date) DESC, vote.congress DESC, vote.chamber
        LIMIT 1;
    ELSE
        v_chamber := lower(btrim(scope_chamber));
        v_congress := scope_congress;
    END IF;

    IF v_chamber IS NULL OR v_congress IS NULL THEN
        RETURN;
    END IF;

    IF v_chamber NOT IN ('house', 'senate') OR v_congress <= 0 THEN
        RAISE EXCEPTION
            'invalid federal voting-alignment scope: chamber %, Congress %',
            v_chamber,
            v_congress
            USING ERRCODE = '22023';
    END IF;

    v_limit := LEAST(
        GREATEST(COALESCE(result_limit_per_side, 6), 1),
        12
    );

    RETURN QUERY
    WITH target_votes AS MATERIALIZED (
        SELECT
            vote.roll_call_source_record_id,
            vote.vote_cast,
            vote.vote_date,
            vote.source_name,
            vote.source_system_key,
            vote.source_catalog_slug,
            vote.source_endpoint_slug,
            vote.source_url,
            vote.source_updated_at
        FROM public.canonical_verified_federal_roll_call_votes_v1 AS vote
        WHERE vote.person_id = v_person_id
          AND vote.chamber = v_chamber
          AND vote.congress = v_congress
          AND vote.vote_cast IN ('yea', 'nay')
    ),
    scored AS (
        SELECT
            peer_vote.person_id AS peer_person_id,
            count(*) FILTER (
                WHERE peer_vote.vote_cast = target_vote.vote_cast
            ) AS agree_count,
            count(*) FILTER (
                WHERE peer_vote.vote_cast <> target_vote.vote_cast
            ) AS differ_count,
            count(*) AS shared_substantive_count,
            round(
                count(*) FILTER (
                    WHERE peer_vote.vote_cast = target_vote.vote_cast
                )::numeric / NULLIF(count(*), 0),
                3
            ) AS agreement_rate,
            min(target_vote.vote_date) AS first_shared_vote_date,
            max(target_vote.vote_date) AS last_shared_vote_date,
            max(target_vote.source_name) AS source_name,
            max(GREATEST(
                target_vote.source_updated_at,
                peer_vote_source.last_seen_at
            )) AS source_updated_at
        FROM target_votes AS target_vote
        JOIN public.person_roll_call_votes AS peer_vote
          ON peer_vote.roll_call_source_record_id =
                target_vote.roll_call_source_record_id
         AND peer_vote.person_id <> v_person_id
         AND peer_vote.vote_cast IN ('yea', 'nay')
        JOIN public.people AS peer_person
          ON peer_person.id = peer_vote.person_id
         AND peer_person.status = 'active'
        JOIN public.source_records AS peer_vote_source
          ON peer_vote_source.id = peer_vote.source_record_id
         AND peer_vote_source.person_id = peer_vote.person_id
         AND peer_vote_source.record_type = 'person_roll_call_vote'
         AND peer_vote_source.record_status = 'active'
         AND peer_vote_source.retired_at IS NULL
         AND peer_vote_source.verified_lane = 'verified'
         AND peer_vote_source.source_system_key =
                target_vote.source_system_key
         AND peer_vote_source.source_catalog_slug =
                target_vote.source_catalog_slug
         AND peer_vote_source.source_endpoint_slug =
                target_vote.source_endpoint_slug
         AND peer_vote_source.source_url = target_vote.source_url
        GROUP BY peer_vote.person_id
        HAVING count(*) >= 10
    ),
    ranked AS (
        SELECT
            score.*,
            row_number() OVER (
                ORDER BY
                    score.agreement_rate DESC,
                    score.shared_substantive_count DESC,
                    score.peer_person_id
            ) AS aligned_rank,
            row_number() OVER (
                ORDER BY
                    score.agreement_rate,
                    score.shared_substantive_count DESC,
                    score.peer_person_id
            ) AS differing_rank
        FROM scored AS score
    )
    SELECT
        ranked.peer_person_id,
        COALESCE(header.full_name, peer.primary_name),
        header.current_office,
        header.party,
        header.state,
        header.district,
        v_chamber,
        v_congress,
        ranked.agree_count,
        ranked.differ_count,
        ranked.shared_substantive_count,
        ranked.agreement_rate,
        ranked.first_shared_vote_date,
        ranked.last_shared_vote_date,
        ranked.aligned_rank,
        ranked.differing_rank,
        ranked.source_name,
        ranked.source_updated_at
    FROM ranked
    JOIN public.people AS peer
      ON peer.id = ranked.peer_person_id
     AND peer.status = 'active'
    LEFT JOIN LATERAL public.get_canonical_politician_header(
        ranked.peer_person_id
    ) AS header ON true
    WHERE ranked.aligned_rank <= v_limit
       OR ranked.differing_rank <= v_limit
    ORDER BY
        LEAST(ranked.aligned_rank, ranked.differing_rank),
        ranked.aligned_rank,
        ranked.differing_rank,
        ranked.peer_person_id;
END
$function$;

CREATE FUNCTION public.get_canonical_federal_voting_comparison_v1(
    p_id uuid,
    peer_id uuid,
    scope_chamber text DEFAULT NULL,
    scope_congress integer DEFAULT NULL,
    comparison_filter text DEFAULT NULL,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    roll_call_id text,
    chamber text,
    congress integer,
    session smallint,
    roll_call_number integer,
    vote_date date,
    question text,
    vote_result text,
    person_vote_cast text,
    peer_vote_cast text,
    comparison text,
    source_name text,
    source_url text,
    source_updated_at timestamptz,
    measures jsonb
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
    v_peer_count integer;
    v_peer_person_id uuid;
    v_chamber text;
    v_congress integer;
    v_filter text;
    v_limit integer;
    v_offset integer;
BEGIN
    SELECT
        count(DISTINCT resolved.person_id),
        (array_agg(
            DISTINCT resolved.person_id
            ORDER BY resolved.person_id
        ))[1]
    INTO v_person_count, v_person_id
    FROM public.get_canonical_person_legacy_ids(p_id) AS resolved;

    SELECT
        count(DISTINCT resolved.person_id),
        (array_agg(
            DISTINCT resolved.person_id
            ORDER BY resolved.person_id
        ))[1]
    INTO v_peer_count, v_peer_person_id
    FROM public.get_canonical_person_legacy_ids(peer_id) AS resolved;

    IF v_person_count = 0 OR v_peer_count = 0 THEN
        RETURN;
    END IF;

    IF v_person_count <> 1 OR v_peer_count <> 1 THEN
        RAISE EXCEPTION
            'canonical voting-comparison resolution returned target % / peer % people',
            v_person_count,
            v_peer_count
            USING ERRCODE = '21000';
    END IF;

    IF v_person_id = v_peer_person_id THEN
        RAISE EXCEPTION
            'a federal voting comparison requires two different canonical people'
            USING ERRCODE = '22023';
    END IF;

    IF (NULLIF(btrim(scope_chamber), '') IS NULL)
       IS DISTINCT FROM (scope_congress IS NULL) THEN
        RAISE EXCEPTION
            'scope_chamber and scope_congress must be supplied together'
            USING ERRCODE = '22023';
    END IF;

    IF scope_chamber IS NULL THEN
        SELECT target_vote.chamber, target_vote.congress
        INTO v_chamber, v_congress
        FROM public.canonical_verified_federal_roll_call_votes_v1 AS target_vote
        JOIN public.person_roll_call_votes AS peer_vote
          ON peer_vote.roll_call_source_record_id =
                target_vote.roll_call_source_record_id
         AND peer_vote.person_id = v_peer_person_id
         AND peer_vote.vote_cast IN ('yea', 'nay')
        JOIN public.people AS peer_person
          ON peer_person.id = peer_vote.person_id
         AND peer_person.status = 'active'
        JOIN public.source_records AS peer_vote_source
          ON peer_vote_source.id = peer_vote.source_record_id
         AND peer_vote_source.person_id = peer_vote.person_id
         AND peer_vote_source.record_type = 'person_roll_call_vote'
         AND peer_vote_source.record_status = 'active'
         AND peer_vote_source.retired_at IS NULL
         AND peer_vote_source.verified_lane = 'verified'
         AND peer_vote_source.source_system_key =
                target_vote.source_system_key
         AND peer_vote_source.source_catalog_slug =
                target_vote.source_catalog_slug
         AND peer_vote_source.source_endpoint_slug =
                target_vote.source_endpoint_slug
         AND peer_vote_source.source_url = target_vote.source_url
        WHERE target_vote.person_id = v_person_id
          AND target_vote.vote_cast IN ('yea', 'nay')
        GROUP BY target_vote.chamber, target_vote.congress
        ORDER BY
            max(target_vote.vote_date) DESC,
            target_vote.congress DESC,
            target_vote.chamber
        LIMIT 1;
    ELSE
        v_chamber := lower(btrim(scope_chamber));
        v_congress := scope_congress;
    END IF;

    IF v_chamber IS NULL OR v_congress IS NULL THEN
        RETURN;
    END IF;

    IF v_chamber NOT IN ('house', 'senate') OR v_congress <= 0 THEN
        RAISE EXCEPTION
            'invalid federal voting-comparison scope: chamber %, Congress %',
            v_chamber,
            v_congress
            USING ERRCODE = '22023';
    END IF;

    v_filter := NULLIF(lower(btrim(coalesce(comparison_filter, ''))), '');
    IF v_filter IS NOT NULL AND v_filter NOT IN ('agree', 'differ') THEN
        RAISE EXCEPTION
            'comparison_filter must be agree, differ, or null'
            USING ERRCODE = '22023';
    END IF;

    v_limit := LEAST(GREATEST(COALESCE(result_limit, 26), 0), 51);
    v_offset := LEAST(GREATEST(COALESCE(result_offset, 0), 0), 5000);

    RETURN QUERY
    WITH shared_votes AS (
        SELECT
            target_vote.roll_call_source_record_id,
            target_vote.canonical_roll_call_key,
            target_vote.chamber,
            target_vote.congress,
            target_vote.session,
            target_vote.roll_call_number,
            target_vote.vote_date,
            target_vote.question,
            target_vote.vote_result,
            target_vote.vote_cast AS person_vote_cast,
            peer_vote.vote_cast AS peer_vote_cast,
            CASE
                WHEN target_vote.vote_cast = peer_vote.vote_cast THEN 'agree'
                ELSE 'differ'
            END AS comparison,
            target_vote.source_name,
            target_vote.source_url,
            GREATEST(
                target_vote.source_updated_at,
                peer_vote_source.last_seen_at
            ) AS source_updated_at
        FROM public.canonical_verified_federal_roll_call_votes_v1 AS target_vote
        JOIN public.person_roll_call_votes AS peer_vote
          ON peer_vote.roll_call_source_record_id =
                target_vote.roll_call_source_record_id
         AND peer_vote.person_id = v_peer_person_id
         AND peer_vote.vote_cast IN ('yea', 'nay')
        JOIN public.people AS peer_person
          ON peer_person.id = peer_vote.person_id
         AND peer_person.status = 'active'
        JOIN public.source_records AS peer_vote_source
          ON peer_vote_source.id = peer_vote.source_record_id
         AND peer_vote_source.person_id = peer_vote.person_id
         AND peer_vote_source.record_type = 'person_roll_call_vote'
         AND peer_vote_source.record_status = 'active'
         AND peer_vote_source.retired_at IS NULL
         AND peer_vote_source.verified_lane = 'verified'
         AND peer_vote_source.source_system_key =
                target_vote.source_system_key
         AND peer_vote_source.source_catalog_slug =
                target_vote.source_catalog_slug
         AND peer_vote_source.source_endpoint_slug =
                target_vote.source_endpoint_slug
         AND peer_vote_source.source_url = target_vote.source_url
        WHERE target_vote.person_id = v_person_id
          AND target_vote.chamber = v_chamber
          AND target_vote.congress = v_congress
          AND target_vote.vote_cast IN ('yea', 'nay')
    )
    SELECT
        shared_vote.canonical_roll_call_key,
        shared_vote.chamber,
        shared_vote.congress,
        shared_vote.session,
        shared_vote.roll_call_number,
        shared_vote.vote_date,
        shared_vote.question,
        shared_vote.vote_result,
        CASE shared_vote.person_vote_cast
            WHEN 'yea' THEN 'Yea'
            WHEN 'nay' THEN 'Nay'
        END,
        CASE shared_vote.peer_vote_cast
            WHEN 'yea' THEN 'Yea'
            WHEN 'nay' THEN 'Nay'
        END,
        shared_vote.comparison,
        shared_vote.source_name,
        shared_vote.source_url,
        shared_vote.source_updated_at,
        COALESCE(measure_set.measures, '[]'::jsonb)
    FROM shared_votes AS shared_vote
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
            FROM public.legislative_roll_call_measure_links AS measure_link
            JOIN public.legislative_measures AS measure
              ON measure.source_record_id = measure_link.measure_source_record_id
             AND measure.congress = shared_vote.congress
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
            WHERE measure_link.roll_call_source_record_id =
                    shared_vote.roll_call_source_record_id
              AND measure_link.link_basis =
                    'exact_official_measure_identifier'
            ORDER BY
                measure.measure_kind,
                measure.measure_type,
                measure.measure_number,
                measure.canonical_measure_key
            LIMIT 20
        ) AS bounded_measure
    ) AS measure_set ON true
    WHERE v_filter IS NULL OR shared_vote.comparison = v_filter
    ORDER BY
        shared_vote.vote_date DESC,
        shared_vote.canonical_roll_call_key,
        shared_vote.roll_call_source_record_id
    LIMIT v_limit
    OFFSET v_offset;
END
$function$;

REVOKE EXECUTE ON FUNCTION public.get_canonical_federal_voting_summary_v1(
    uuid
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_federal_voting_alignment_v1(
    uuid,
    text,
    integer,
    integer
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_federal_voting_comparison_v1(
    uuid,
    uuid,
    text,
    integer,
    text,
    integer,
    integer
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_federal_voting_summary_v1(
    uuid
) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_federal_voting_alignment_v1(
    uuid,
    text,
    integer,
    integer
) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_federal_voting_comparison_v1(
    uuid,
    uuid,
    text,
    integer,
    text,
    integer,
    integer
) TO anon, authenticated;

DO $migration_postconditions$
DECLARE
    v_function_oid oid;
    v_signature text;
BEGIN
    FOREACH v_signature IN ARRAY ARRAY[
        'public.get_canonical_federal_voting_summary_v1(uuid)',
        'public.get_canonical_federal_voting_alignment_v1(uuid,text,integer,integer)',
        'public.get_canonical_federal_voting_comparison_v1(uuid,uuid,text,integer,text,integer,integer)'
    ] LOOP
        v_function_oid := to_regprocedure(v_signature);

        IF v_function_oid IS NULL
           OR NOT (
                SELECT function_state.prosecdef
                FROM pg_proc AS function_state
                WHERE function_state.oid = v_function_oid
           )
           OR NOT has_function_privilege('anon', v_function_oid, 'EXECUTE')
           OR NOT has_function_privilege(
                'authenticated',
                v_function_oid,
                'EXECUTE'
           )
           OR EXISTS (
                SELECT 1
                FROM aclexplode(
                    (SELECT proacl FROM pg_proc WHERE oid = v_function_oid)
                ) AS acl
                WHERE acl.grantee = 0
                  AND acl.privilege_type = 'EXECUTE'
           ) THEN
            RAISE EXCEPTION
                'federal voting analytics RPC security contract was not installed: %',
                v_signature
                USING ERRCODE = '42501';
        END IF;
    END LOOP;

    IF has_table_privilege(
        'anon',
        'public.canonical_verified_federal_roll_call_votes_v1',
        'SELECT'
    )
       OR has_table_privilege(
            'authenticated',
            'public.canonical_verified_federal_roll_call_votes_v1',
            'SELECT'
       )
       OR has_table_privilege(
            'service_role',
            'public.canonical_verified_federal_roll_call_votes_v1',
            'SELECT'
       )
       OR has_table_privilege('anon', 'public.source_records', 'SELECT')
       OR has_table_privilege('authenticated', 'public.source_records', 'SELECT')
       OR has_table_privilege(
            'anon',
            'public.legislative_roll_calls',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_roll_calls',
            'SELECT'
       )
       OR has_table_privilege(
            'anon',
            'public.person_roll_call_votes',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.person_roll_call_votes',
            'SELECT'
       )
       OR has_table_privilege(
            'anon',
            'public.legislative_measures',
            'SELECT'
       )
       OR has_table_privilege(
            'authenticated',
            'public.legislative_measures',
            'SELECT'
       )
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
            'federal voting analytics opened an internal view or private table'
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
    '0038_canonical_federal_voting_analytics',
    38,
    'Expose bounded canonical federal vote summaries, alignment rankings, and inspectable pair evidence.',
    jsonb_build_object(
        'internal_read_model',
            'canonical_verified_federal_roll_call_votes_v1',
        'public_rpcs', jsonb_build_array(
            'get_canonical_federal_voting_summary_v1',
            'get_canonical_federal_voting_alignment_v1',
            'get_canonical_federal_voting_comparison_v1'
        ),
        'official_sources', jsonb_build_array(
            'house-clerk-roll-call-xml',
            'senate-roll-call-xml'
        ),
        'identity_key', 'person_id',
        'alignment_vote_casts', jsonb_build_array('yea', 'nay'),
        'alignment_minimum_shared_votes', 10,
        'maximum_ranked_peers_per_side', 12,
        'maximum_comparison_page_size', 51,
        'maximum_measures_per_comparison_vote', 20,
        'legacy_vote_rows_included', false,
        'direct_private_table_access_created', false,
        'scraper_write_contract_changed', false,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
