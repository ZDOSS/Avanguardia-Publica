-- 0010_canonical_rollup_shared_signals.sql
--
-- Makes canonical politician rollups tolerant of minor contact formatting drift.
-- Rows can now collapse when they share a normalized full name and either a stable
-- federal identity signal, such as Bioguide, or the strongest matching pair of
-- official contact signals. Also re-runs the congressional House location repair
-- for rows inserted after migration 0009 was applied.

UPDATE public.politicians AS p
SET
    state = COALESCE(
        substring(upper(btrim(p.district)) from '^([A-Z]{2})-'),
        substring(upper(coalesce(p.current_office, '')) from 'U\.?S\.? DISTRICT ([A-Z]{2})-'),
        p.state
    ),
    district = COALESCE(
        NULLIF(regexp_replace(upper(btrim(coalesce(p.district, ''))), '^[A-Z]{2}-', ''), ''),
        substring(upper(coalesce(p.current_office, '')) from 'U\.?S\.? DISTRICT [A-Z]{2}-([0-9A-Z-]+)'),
        p.district
    ),
    government_level = 'federal',
    government_branch = 'legislative',
    office_type = 'representative',
    jurisdiction = 'US'
FROM public.contact_info AS ci
WHERE ci.politician_id = p.id
  AND lower(coalesce(ci.official_website, '')) LIKE '%.house.gov%'
  AND lower(coalesce(p.current_office, '')) LIKE '%representative%'
  AND (
      upper(coalesce(p.district, '')) ~ '^[A-Z]{2}-'
      OR upper(coalesce(p.current_office, '')) ~ 'U\.?S\.? DISTRICT [A-Z]{2}-'
  );

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
                regexp_replace(
                    regexp_replace(lower(btrim(coalesce(ci.office_address, ''))), '[^a-z0-9]+', ' ', 'g'),
                    '\s+',
                    ' ',
                    'g'
                ),
                ''
            ) AS address_key,
            NULLIF(lower(btrim(coalesce(p.bioguide_id, ''))), '') AS bioguide_key,
            NULLIF(upper(btrim(coalesce(p.state, ''))), '') AS raw_state,
            NULLIF(upper(btrim(coalesce(p.district, ''))), '') AS raw_district,
            lower(btrim(coalesce(p.government_level, ''))) AS raw_government_level,
            lower(btrim(coalesce(p.office_type, ''))) AS raw_office_type,
            upper(coalesce(p.current_office, '')) AS office_upper,
            lower(coalesce(p.current_office, '')) AS office_lower
        FROM public.politicians AS p
        LEFT JOIN public.contact_info AS ci ON ci.politician_id = p.id
    ),
    keyed AS (
        SELECT
            ck.*,
            CASE
                WHEN ck.raw_district ~ '^[A-Z]{2}-' THEN substring(ck.raw_district from '^([A-Z]{2})-')
                WHEN ck.office_upper ~ 'U\.?S\.? DISTRICT [A-Z]{2}-' THEN substring(ck.office_upper from 'U\.?S\.? DISTRICT ([A-Z]{2})-')
                WHEN ck.raw_state = 'US' THEN NULL
                ELSE ck.raw_state
            END AS match_state,
            CASE
                WHEN ck.raw_district ~ '^[A-Z]{2}-' THEN regexp_replace(ck.raw_district, '^[A-Z]{2}-', '')
                WHEN ck.office_upper ~ 'U\.?S\.? DISTRICT [A-Z]{2}-' THEN substring(ck.office_upper from 'U\.?S\.? DISTRICT [A-Z]{2}-([0-9A-Z-]+)')
                ELSE ck.raw_district
            END AS match_district,
            CASE
                WHEN ck.raw_government_level = 'state'
                  AND ck.office_lower LIKE '%representative%'
                  AND (
                      ck.website_key LIKE '%.house.gov%'
                      OR ck.office_upper ~ 'U\.?S\.? DISTRICT [A-Z]{2}-'
                  )
                    THEN 'federal'
                ELSE NULLIF(ck.raw_government_level, '')
            END AS match_government_level,
            NULLIF(ck.raw_office_type, '') AS match_office_type
        FROM contact_keys AS ck
    ),
    matchable AS (
        SELECT
            k.*,
            CASE
                WHEN k.name_key IS NOT NULL AND k.bioguide_key IS NOT NULL
                    THEN k.name_key || '|bio:' || k.bioguide_key
                WHEN k.name_key IS NOT NULL
                  AND k.phone_key IS NOT NULL AND length(k.phone_key) >= 7
                  AND k.website_key IS NOT NULL AND length(k.website_key) >= 4
                    THEN k.name_key || '|phone:' || k.phone_key || '|web:' || k.website_key
                WHEN k.name_key IS NOT NULL
                  AND k.phone_key IS NOT NULL AND length(k.phone_key) >= 7
                  AND k.address_key IS NOT NULL AND length(k.address_key) >= 10
                    THEN k.name_key || '|phone:' || k.phone_key || '|addr:' || k.address_key
                WHEN k.name_key IS NOT NULL
                  AND k.website_key IS NOT NULL AND length(k.website_key) >= 4
                  AND k.address_key IS NOT NULL AND length(k.address_key) >= 10
                    THEN k.name_key || '|web:' || k.website_key || '|addr:' || k.address_key
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
           AND count(DISTINCT match_state) FILTER (WHERE match_state IS NOT NULL AND btrim(match_state) <> '') <= 1
           AND count(DISTINCT match_district) FILTER (WHERE match_district IS NOT NULL AND btrim(match_district) <> '') <= 1
           AND count(DISTINCT match_government_level) FILTER (
                WHERE match_government_level IS NOT NULL AND btrim(match_government_level) <> ''
           ) <= 1
           AND count(DISTINCT match_office_type) FILTER (
                WHERE match_office_type IS NOT NULL AND btrim(match_office_type) <> ''
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
