-- 0006_supabase_best_practices.sql
--
-- Aligns the live database with the current Supabase/Postgres read paths:
--   * generated full-text search vector for browser search
--   * composite indexes for profile spoke pagination
--   * schema parity indexes that schema.sql now includes for fresh bootstraps
--   * hardened SECURITY DEFINER RPCs with an empty search_path and fully-qualified tables
--
-- Idempotent and safe to re-run. Apply manually after existing migrations.

ALTER TABLE politicians
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(full_name, '') || ' ' ||
            coalesce(current_office, '') || ' ' ||
            coalesce(party, '') || ' ' ||
            coalesce(array_to_string(aliases, ' '), '')
        )
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_politicians_full_name
    ON politicians (full_name);

CREATE INDEX IF NOT EXISTS idx_politicians_external_ids
    ON politicians USING gin (external_ids);

CREATE INDEX IF NOT EXISTS idx_politicians_search_vector
    ON politicians USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_financial_disclosures_politician_filing_date
    ON financial_disclosures (politician_id, filing_date DESC, id);

CREATE INDEX IF NOT EXISTS idx_campaign_donors_politician
    ON campaign_donors (politician_id);

CREATE INDEX IF NOT EXISTS idx_campaign_donors_politician_donation_date
    ON campaign_donors (politician_id, donation_date DESC NULLS LAST, id);

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_vote_date
    ON voting_records (politician_id, vote_date DESC, id);

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_vote_cast_vote_date
    ON voting_records (politician_id, vote_cast, vote_date DESC, id);

CREATE INDEX IF NOT EXISTS idx_unconfirmed_mentions_politician_created
    ON unconfirmed_mentions (politician_id, created_at DESC);

CREATE OR REPLACE FUNCTION get_shared_donors(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    shared_donor_count bigint,
    shared_total_amount numeric
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    WITH mine AS (
        SELECT DISTINCT lower(btrim(cd.donor_name)) AS dn
        FROM public.campaign_donors AS cd
        WHERE cd.politician_id = p_id
          AND cd.donor_name IS NOT NULL
          AND btrim(cd.donor_name) <> ''
    )
    SELECT p.id, p.full_name, p.current_office, p.party,
           COUNT(DISTINCT lower(btrim(cd.donor_name))) AS shared_donor_count,
           COALESCE(SUM(cd.amount), 0) AS shared_total_amount
    FROM public.campaign_donors AS cd
    JOIN mine ON lower(btrim(cd.donor_name)) = mine.dn
    JOIN public.politicians AS p ON p.id = cd.politician_id
    WHERE cd.politician_id <> p_id
    GROUP BY p.id, p.full_name, p.current_office, p.party
    ORDER BY shared_donor_count DESC, shared_total_amount DESC
    LIMIT 15;
$$;

CREATE OR REPLACE FUNCTION get_covoting(p_id uuid)
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
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    WITH mine AS (
        SELECT DISTINCT ON (vr.roll_call_id) vr.roll_call_id, vr.vote_cast
        FROM public.voting_records AS vr
        WHERE vr.politician_id = p_id
          AND vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
        ORDER BY vr.roll_call_id, vr.vote_cast
    ),
    theirs AS (
        SELECT DISTINCT ON (vr.politician_id, vr.roll_call_id)
               vr.politician_id, vr.roll_call_id, vr.vote_cast
        FROM public.voting_records AS vr
        WHERE vr.politician_id <> p_id
          AND vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
        ORDER BY vr.politician_id, vr.roll_call_id, vr.vote_cast
    )
    SELECT p.id, p.full_name, p.current_office, p.party,
           COUNT(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast) AS agree_count,
           COUNT(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast) AS disagree_count,
           COUNT(*) AS shared_total,
           ROUND(
               COUNT(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast)::numeric
               / NULLIF(COUNT(*), 0),
               3
           ) AS agreement_rate
    FROM theirs
    JOIN mine ON mine.roll_call_id = theirs.roll_call_id
    JOIN public.politicians AS p ON p.id = theirs.politician_id
    GROUP BY p.id, p.full_name, p.current_office, p.party
    ORDER BY shared_total DESC, GREATEST(
        COUNT(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast),
        COUNT(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast)
    ) DESC
    LIMIT 30;
$$;

CREATE OR REPLACE FUNCTION get_network_ties(p_id uuid)
RETURNS TABLE (
    related_name text,
    related_politician_id uuid,
    relationship_type text,
    source_api text,
    url text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT r.related_name, r.related_politician_id, r.relationship_type, r.source_api, r.url
    FROM public.relationships AS r
    WHERE r.politician_id = p_id
    ORDER BY (r.related_politician_id IS NULL), r.related_name
    LIMIT 30;
$$;

REVOKE EXECUTE ON FUNCTION get_shared_donors(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_covoting(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION get_network_ties(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION get_shared_donors(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_covoting(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_network_ties(uuid) TO anon, authenticated;
