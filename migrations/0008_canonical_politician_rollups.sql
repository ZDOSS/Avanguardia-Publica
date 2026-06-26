-- 0008_canonical_politician_rollups.sql
--
-- Adds conservative, read-time duplicate rollups for politician directory/search/profile
-- views. This does not merge or delete source rows. It only exposes canonical read RPCs
-- that collapse rows when they share a normalized full name and at least two normalized
-- official contact signals, with no conflicting state/classification fields.
--
-- Idempotent and safe to re-run manually in Supabase SQL editor.

CREATE OR REPLACE FUNCTION public.resolve_canonical_politician_ids()
RETURNS TABLE (
    id uuid,
    canonical_id uuid,
    duplicate_count bigint
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    WITH contact_keys AS (
        SELECT
            p.id,
            p.state,
            p.district,
            p.government_level,
            p.office_type,
            p.bioguide_id,
            p.external_ids,
            p.last_updated,
            ci.politician_id IS NOT NULL AS has_contact,
            NULLIF(regexp_replace(lower(btrim(p.full_name)), '\s+', ' ', 'g'), '') AS name_key,
            NULLIF(regexp_replace(coalesce(ci.phone_number, ''), '\D', '', 'g'), '') AS phone_key,
            NULLIF(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(lower(btrim(coalesce(ci.official_website, ''))), '^https?://', ''),
                        '^www\.',
                        ''
                    ),
                    '/+$',
                    ''
                ),
                ''
            ) AS website_key,
            NULLIF(
                regexp_replace(lower(btrim(coalesce(ci.office_address, ''))), '\s+', ' ', 'g'),
                ''
            ) AS address_key
        FROM public.politicians AS p
        LEFT JOIN public.contact_info AS ci ON ci.politician_id = p.id
    ),
    keyed AS (
        SELECT
            ck.*,
            (
                CASE WHEN ck.phone_key IS NOT NULL AND length(ck.phone_key) >= 7 THEN 1 ELSE 0 END
              + CASE WHEN ck.website_key IS NOT NULL AND length(ck.website_key) >= 4 THEN 1 ELSE 0 END
              + CASE WHEN ck.address_key IS NOT NULL AND length(ck.address_key) >= 10 THEN 1 ELSE 0 END
            ) AS contact_signal_count,
            concat_ws(
                '|',
                CASE WHEN ck.phone_key IS NOT NULL AND length(ck.phone_key) >= 7 THEN 'phone:' || ck.phone_key END,
                CASE WHEN ck.website_key IS NOT NULL AND length(ck.website_key) >= 4 THEN 'web:' || ck.website_key END,
                CASE WHEN ck.address_key IS NOT NULL AND length(ck.address_key) >= 10 THEN 'addr:' || ck.address_key END
            ) AS contact_signature
        FROM contact_keys AS ck
    ),
    matchable AS (
        SELECT
            k.*,
            CASE
                WHEN k.name_key IS NOT NULL AND k.contact_signal_count >= 2
                    THEN k.name_key || '|' || k.contact_signature
                ELSE NULL
            END AS duplicate_key
        FROM keyed AS k
    ),
    eligible_groups AS (
        SELECT duplicate_key
        FROM matchable
        WHERE duplicate_key IS NOT NULL
        GROUP BY duplicate_key
        HAVING count(*) > 1
           AND count(DISTINCT lower(btrim(state))) FILTER (WHERE state IS NOT NULL AND btrim(state) <> '') <= 1
           AND count(DISTINCT lower(btrim(district))) FILTER (WHERE district IS NOT NULL AND btrim(district) <> '') <= 1
           AND count(DISTINCT lower(btrim(government_level))) FILTER (
                WHERE government_level IS NOT NULL AND btrim(government_level) <> ''
           ) <= 1
           AND count(DISTINCT lower(btrim(office_type))) FILTER (
                WHERE office_type IS NOT NULL AND btrim(office_type) <> ''
           ) <= 1
    ),
    scored AS (
        SELECT
            m.id,
            m.duplicate_key,
            m.last_updated,
            (
                COALESCE(fc.row_count, 0) * 25
              + COALESCE(dc.row_count, 0)
              + COALESCE(vc.row_count, 0)
              + COALESCE(mc.row_count, 0)
              + COALESCE(rc.row_count, 0) * 5
              + CASE WHEN m.bioguide_id IS NOT NULL AND btrim(m.bioguide_id) <> '' THEN 50 ELSE 0 END
              + CASE WHEN m.external_ids <> '{}'::jsonb THEN 10 ELSE 0 END
              + CASE WHEN m.has_contact THEN 5 ELSE 0 END
            ) AS richness_score,
            count(*) OVER (PARTITION BY m.duplicate_key) AS group_count
        FROM matchable AS m
        JOIN eligible_groups AS eg ON eg.duplicate_key = m.duplicate_key
        LEFT JOIN LATERAL (
            SELECT count(*) AS row_count
            FROM public.financial_disclosures AS fd
            WHERE fd.politician_id = m.id
        ) AS fc ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS row_count
            FROM public.campaign_donors AS cd
            WHERE cd.politician_id = m.id
        ) AS dc ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS row_count
            FROM public.voting_records AS vr
            WHERE vr.politician_id = m.id
        ) AS vc ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS row_count
            FROM public.unconfirmed_mentions AS um
            WHERE um.politician_id = m.id
        ) AS mc ON true
        LEFT JOIN LATERAL (
            SELECT count(*) AS row_count
            FROM public.relationships AS r
            WHERE r.politician_id = m.id
        ) AS rc ON true
    ),
    ranked AS (
        SELECT
            s.*,
            row_number() OVER (
                PARTITION BY s.duplicate_key
                ORDER BY s.richness_score DESC, s.last_updated DESC NULLS LAST, s.id
            ) AS duplicate_rank
        FROM scored AS s
    ),
    canonical_groups AS (
        SELECT r.duplicate_key, r.id AS canonical_id, r.group_count AS duplicate_count
        FROM ranked AS r
        JOIN eligible_groups AS eg ON eg.duplicate_key = r.duplicate_key
        WHERE r.duplicate_rank = 1
    )
    SELECT
        m.id,
        COALESCE(cg.canonical_id, m.id) AS canonical_id,
        COALESCE(cg.duplicate_count, 1) AS duplicate_count
    FROM matchable AS m
    LEFT JOIN canonical_groups AS cg ON cg.duplicate_key = m.duplicate_key;
$$;

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
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    WITH params AS (
        SELECT NULLIF(btrim(search_query), '') AS q
    ),
    matching_canonical_ids AS (
        SELECT
            m.canonical_id,
            bool_or(
                params.q IS NULL
                OR COALESCE(p.search_vector @@ websearch_to_tsquery('english', params.q), false)
            ) AS matches_search
        FROM public.resolve_canonical_politician_ids() AS m
        JOIN public.politicians AS p ON p.id = m.id
        CROSS JOIN params
        GROUP BY m.canonical_id
    )
    SELECT
        p.id,
        p.full_name,
        p.current_office,
        p.party,
        p.state,
        p.district,
        p.government_level,
        p.government_branch,
        p.office_type,
        p.jurisdiction
    FROM matching_canonical_ids AS m
    JOIN public.politicians AS p ON p.id = m.canonical_id
    WHERE m.matches_search
    ORDER BY p.full_name
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 1000), 0), 1000)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_politician_header(p_id uuid)
RETURNS TABLE (
    id uuid,
    full_name text,
    current_office text,
    party text,
    state text,
    district text,
    last_updated timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT
        p.id,
        p.full_name,
        p.current_office,
        p.party,
        p.state,
        p.district,
        p.last_updated
    FROM public.resolve_canonical_politician_ids() AS m
    JOIN public.politicians AS p ON p.id = m.canonical_id
    WHERE m.id = p_id
    LIMIT 1;
$$;

REVOKE EXECUTE ON FUNCTION public.resolve_canonical_politician_ids() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) TO anon, authenticated;
