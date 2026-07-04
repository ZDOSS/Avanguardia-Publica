-- 0013_search_and_covoting_fixes.sql
--
-- Fixes two production read issues found during Phase 2 validation:
--
-- 1. Canonical search was too strict for initials and partial names because it relied
--    mostly on full-text search. Add prefix/word-prefix matching over normalized names
--    while keeping the canonical one-row-per-person contract.
-- 2. get_covoting timed out because it resolved every voting row before narrowing to
--    the target profile. Rework it to start from the target person's votes and then
--    join outward by roll_call_id.

CREATE INDEX IF NOT EXISTS idx_politicians_full_name_lower_prefix
    ON public.politicians (lower(full_name) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_people_primary_name_lower_prefix
    ON public.people (lower(primary_name) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_voting_records_person_roll_call_active
    ON public.voting_records (person_id, roll_call_id, vote_cast)
    WHERE person_id IS NOT NULL
      AND roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_roll_call_active
    ON public.voting_records (politician_id, roll_call_id, vote_cast)
    WHERE roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call_vote_person_active
    ON public.voting_records (roll_call_id, vote_cast, person_id)
    WHERE roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;

CREATE OR REPLACE FUNCTION public.get_canonical_politician_summaries(
    search_query text DEFAULT NULL,
    result_limit integer DEFAULT 1000,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    full_name text,
    current_office text,
    party text,
    state text,
    district text,
    government_level text,
    government_branch text,
    office_type text,
    jurisdiction text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH raw_params AS (
        SELECT
            NULLIF(btrim(search_query), '') AS q,
            NULLIF(
                btrim(
                    regexp_replace(
                        lower(btrim(coalesce(search_query, ''))),
                        '[^a-z0-9]+',
                        ' ',
                        'g'
                    )
                ),
                ''
            ) AS q_norm,
            NULLIF(
                regexp_replace(
                    lower(btrim(coalesce(search_query, ''))),
                    '[^a-z0-9]+',
                    '',
                    'g'
                ),
                ''
            ) AS q_compact
    ),
    params AS (
        SELECT
            q,
            q_norm,
            q_compact,
            CASE
                WHEN q IS NULL THEN NULL::tsquery
                ELSE websearch_to_tsquery('english', q)
            END AS q_ts
        FROM raw_params
    ),
    mapped_profiles AS (
        SELECT
            l.person_id,
            l.legacy_politician_id,
            l.legacy_politician_id = l.canonical_politician_id AS is_canonical
        FROM public.legacy_profile_redirects AS l
        JOIN public.people AS pe ON pe.id = l.person_id
        WHERE pe.status = 'active'

        UNION ALL

        SELECT
            p.id AS person_id,
            p.id AS legacy_politician_id,
            true AS is_canonical
        FROM public.politicians AS p
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.legacy_profile_redirects AS l
            WHERE l.legacy_politician_id = p.id
        )
    ),
    search_candidates AS (
        SELECT
            mp.person_id,
            p.search_vector,
            lower(coalesce(pe.primary_name, p.full_name, '')) AS display_lower,
            lower(coalesce(p.full_name, '')) AS legacy_lower,
            btrim(
                regexp_replace(
                    btrim(lower(coalesce(pe.primary_name, p.full_name, ''))),
                    '[^a-z0-9]+',
                    ' ',
                    'g'
                )
            ) AS display_norm,
            btrim(
                regexp_replace(
                    btrim(lower(coalesce(p.full_name, ''))),
                    '[^a-z0-9]+',
                    ' ',
                    'g'
                )
            ) AS legacy_norm,
            regexp_replace(
                lower(coalesce(pe.primary_name, p.full_name, '')),
                '[^a-z0-9]+',
                '',
                'g'
            ) AS display_compact,
            regexp_replace(
                lower(coalesce(p.full_name, '')),
                '[^a-z0-9]+',
                '',
                'g'
            ) AS legacy_compact
        FROM mapped_profiles AS mp
        JOIN public.politicians AS p ON p.id = mp.legacy_politician_id
        LEFT JOIN public.people AS pe ON pe.id = mp.person_id
    ),
    matching_people AS (
        SELECT
            sc.person_id,
            bool_or(
                params.q IS NULL
                OR COALESCE(sc.search_vector @@ params.q_ts, false)
                OR (
                    params.q IS NOT NULL
                    AND (
                        sc.display_lower LIKE lower(params.q) || '%'
                        OR sc.legacy_lower LIKE lower(params.q) || '%'
                    )
                )
                OR (
                    params.q_norm IS NOT NULL
                    AND (
                        sc.display_norm LIKE params.q_norm || '%'
                        OR sc.legacy_norm LIKE params.q_norm || '%'
                        OR sc.display_norm LIKE '% ' || params.q_norm || '%'
                        OR sc.legacy_norm LIKE '% ' || params.q_norm || '%'
                    )
                )
                OR (
                    params.q_compact IS NOT NULL
                    AND (
                        sc.display_compact LIKE params.q_compact || '%'
                        OR sc.legacy_compact LIKE params.q_compact || '%'
                    )
                )
            ) AS matches_search,
            min(
                CASE
                    WHEN params.q IS NULL THEN 3
                    WHEN params.q_norm IS NOT NULL
                     AND (sc.display_norm = params.q_norm OR sc.legacy_norm = params.q_norm)
                        THEN 0
                    WHEN params.q_compact IS NOT NULL
                     AND (sc.display_compact = params.q_compact OR sc.legacy_compact = params.q_compact)
                        THEN 0
                    WHEN params.q IS NOT NULL
                     AND (sc.display_lower LIKE lower(params.q) || '%' OR sc.legacy_lower LIKE lower(params.q) || '%')
                        THEN 1
                    WHEN params.q_norm IS NOT NULL
                     AND (sc.display_norm LIKE params.q_norm || '%' OR sc.legacy_norm LIKE params.q_norm || '%')
                        THEN 1
                    WHEN params.q_compact IS NOT NULL
                     AND (sc.display_compact LIKE params.q_compact || '%' OR sc.legacy_compact LIKE params.q_compact || '%')
                        THEN 1
                    WHEN params.q_norm IS NOT NULL
                     AND (sc.display_norm LIKE '% ' || params.q_norm || '%' OR sc.legacy_norm LIKE '% ' || params.q_norm || '%')
                        THEN 2
                    WHEN COALESCE(sc.search_vector @@ params.q_ts, false)
                        THEN 3
                    ELSE 4
                END
            ) AS search_rank
        FROM search_candidates AS sc
        CROSS JOIN params
        GROUP BY sc.person_id
    ),
    ranked_profiles AS (
        SELECT
            mp.person_id,
            p.*,
            row_number() OVER (
                PARTITION BY mp.person_id
                ORDER BY
                    mp.is_canonical DESC,
                    CASE WHEN NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL THEN 1 ELSE 0 END DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM mapped_profiles AS mp
        JOIN public.politicians AS p ON p.id = mp.legacy_politician_id
    )
    SELECT
        rp.person_id AS id,
        COALESCE(pe.primary_name, rp.full_name) AS full_name,
        rp.current_office,
        rp.party,
        rp.state,
        rp.district,
        rp.government_level,
        rp.government_branch,
        rp.office_type,
        rp.jurisdiction
    FROM matching_people AS m
    JOIN ranked_profiles AS rp
      ON rp.person_id = m.person_id
     AND rp.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = rp.person_id AND pe.status = 'active'
    WHERE m.matches_search
    ORDER BY m.search_rank, COALESCE(pe.primary_name, rp.full_name), rp.person_id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 1000), 0), 1000)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_covoting(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    agree_count bigint,
    disagree_count bigint,
    shared_total bigint,
    agreement_rate numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH target_legacy AS (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target_person AS (
        SELECT person_id
        FROM target_legacy
        LIMIT 1
    ),
    target_vote_candidates AS (
        SELECT
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN target_person AS tp ON tp.person_id = vr.person_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL

        UNION ALL

        SELECT
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN target_legacy AS tl ON tl.legacy_politician_id = vr.politician_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
    ),
    mine AS (
        SELECT DISTINCT ON (roll_call_id)
            roll_call_id,
            vote_cast
        FROM target_vote_candidates
        ORDER BY roll_call_id, vote_cast
    ),
    other_vote_candidates AS (
        SELECT
            COALESCE(vr.person_id, l.person_id) AS person_id,
            vr.roll_call_id,
            vr.vote_cast
        FROM mine
        JOIN public.voting_records AS vr
          ON vr.roll_call_id = mine.roll_call_id
        LEFT JOIN public.legacy_profile_redirects AS l
          ON l.legacy_politician_id = vr.politician_id
        CROSS JOIN target_person AS tp
        WHERE vr.vote_cast IS NOT NULL
          AND COALESCE(vr.person_id, l.person_id) IS NOT NULL
          AND COALESCE(vr.person_id, l.person_id) <> tp.person_id
    ),
    theirs AS (
        SELECT DISTINCT ON (person_id, roll_call_id)
            person_id,
            roll_call_id,
            vote_cast
        FROM other_vote_candidates
        ORDER BY person_id, roll_call_id, vote_cast
    ),
    involved_people AS (
        SELECT DISTINCT person_id
        FROM theirs
    ),
    ranked_headers AS (
        SELECT
            l.person_id,
            p.full_name,
            p.current_office,
            p.party,
            row_number() OVER (
                PARTITION BY l.person_id
                ORDER BY
                    (l.legacy_politician_id = l.canonical_politician_id) DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM involved_people AS i
        JOIN public.legacy_profile_redirects AS l ON l.person_id = i.person_id
        JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        theirs.person_id AS politician_id,
        COALESCE(pe.primary_name, rh.full_name) AS full_name,
        rh.current_office,
        rh.party,
        count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast) AS agree_count,
        count(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast) AS disagree_count,
        count(*) AS shared_total,
        round(
            count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast)::numeric
            / NULLIF(count(*), 0),
            3
        ) AS agreement_rate
    FROM theirs
    JOIN mine ON mine.roll_call_id = theirs.roll_call_id
    JOIN ranked_headers AS rh ON rh.person_id = theirs.person_id AND rh.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = theirs.person_id AND pe.status = 'active'
    GROUP BY theirs.person_id, COALESCE(pe.primary_name, rh.full_name), rh.current_office, rh.party
    ORDER BY shared_total DESC, GREATEST(
        count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast),
        count(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast)
    ) DESC
    LIMIT 30;
$$;

REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_covoting(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_covoting(uuid) TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
