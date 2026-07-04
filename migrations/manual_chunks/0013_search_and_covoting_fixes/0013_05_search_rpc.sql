SET statement_timeout = '30s';

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
            to_tsvector('english', coalesce(pe.primary_name, '')) AS primary_name_search_vector,
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
                OR COALESCE(sc.primary_name_search_vector @@ params.q_ts, false)
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
                      OR COALESCE(sc.primary_name_search_vector @@ params.q_ts, false)
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
