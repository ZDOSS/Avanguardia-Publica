-- 0012_person_aware_profile_spokes.sql
--
-- Phase 2 of docs/canonical_data_and_analytics_plan.md.
--
-- Adds nullable person_id columns to existing profile spokes, backfills them from the
-- canonical identity bridge, and updates read RPCs to prefer canonical person identity
-- while preserving legacy politician_id fallbacks for rollback.

ALTER TABLE public.contact_info
    ADD COLUMN IF NOT EXISTS person_id uuid;
ALTER TABLE public.financial_disclosures
    ADD COLUMN IF NOT EXISTS person_id uuid;
ALTER TABLE public.campaign_donors
    ADD COLUMN IF NOT EXISTS person_id uuid;
ALTER TABLE public.voting_records
    ADD COLUMN IF NOT EXISTS person_id uuid;
ALTER TABLE public.unconfirmed_mentions
    ADD COLUMN IF NOT EXISTS person_id uuid;
ALTER TABLE public.relationships
    ADD COLUMN IF NOT EXISTS person_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'contact_info_person_id_fkey'
          AND conrelid = 'public.contact_info'::regclass
    ) THEN
        ALTER TABLE public.contact_info
            ADD CONSTRAINT contact_info_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'financial_disclosures_person_id_fkey'
          AND conrelid = 'public.financial_disclosures'::regclass
    ) THEN
        ALTER TABLE public.financial_disclosures
            ADD CONSTRAINT financial_disclosures_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'campaign_donors_person_id_fkey'
          AND conrelid = 'public.campaign_donors'::regclass
    ) THEN
        ALTER TABLE public.campaign_donors
            ADD CONSTRAINT campaign_donors_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'voting_records_person_id_fkey'
          AND conrelid = 'public.voting_records'::regclass
    ) THEN
        ALTER TABLE public.voting_records
            ADD CONSTRAINT voting_records_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'unconfirmed_mentions_person_id_fkey'
          AND conrelid = 'public.unconfirmed_mentions'::regclass
    ) THEN
        ALTER TABLE public.unconfirmed_mentions
            ADD CONSTRAINT unconfirmed_mentions_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_person_id_fkey'
          AND conrelid = 'public.relationships'::regclass
    ) THEN
        ALTER TABLE public.relationships
            ADD CONSTRAINT relationships_person_id_fkey
            FOREIGN KEY (person_id) REFERENCES public.people(id) ON DELETE SET NULL;
    END IF;
END $$;

UPDATE public.contact_info AS ci
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE ci.politician_id = l.legacy_politician_id
  AND ci.person_id IS DISTINCT FROM l.person_id;

UPDATE public.financial_disclosures AS fd
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE fd.politician_id = l.legacy_politician_id
  AND fd.person_id IS DISTINCT FROM l.person_id;

UPDATE public.campaign_donors AS cd
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE cd.politician_id = l.legacy_politician_id
  AND cd.person_id IS DISTINCT FROM l.person_id;

UPDATE public.voting_records AS vr
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE vr.politician_id = l.legacy_politician_id
  AND vr.person_id IS DISTINCT FROM l.person_id;

UPDATE public.unconfirmed_mentions AS um
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE um.politician_id = l.legacy_politician_id
  AND um.person_id IS DISTINCT FROM l.person_id;

UPDATE public.relationships AS r
SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
WHERE r.politician_id = l.legacy_politician_id
  AND r.person_id IS DISTINCT FROM l.person_id;

CREATE INDEX IF NOT EXISTS idx_contact_info_person
    ON public.contact_info (person_id);
CREATE INDEX IF NOT EXISTS idx_financial_disclosures_person_filing_date
    ON public.financial_disclosures (person_id, filing_date DESC, id);
CREATE INDEX IF NOT EXISTS idx_campaign_donors_person_donation_date
    ON public.campaign_donors (person_id, donation_date DESC NULLS LAST, id);
CREATE INDEX IF NOT EXISTS idx_campaign_donors_person_donor_lower
    ON public.campaign_donors (person_id, lower(btrim(donor_name)));
CREATE INDEX IF NOT EXISTS idx_voting_records_person_vote_date
    ON public.voting_records (person_id, vote_date DESC, id);
CREATE INDEX IF NOT EXISTS idx_voting_records_person_vote_cast_vote_date
    ON public.voting_records (person_id, vote_cast, vote_date DESC, id);
CREATE INDEX IF NOT EXISTS idx_voting_records_person_roll_call
    ON public.voting_records (person_id, roll_call_id, vote_cast);
CREATE INDEX IF NOT EXISTS idx_unconfirmed_mentions_person_created
    ON public.unconfirmed_mentions (person_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_relationships_person
    ON public.relationships (person_id);

CREATE OR REPLACE FUNCTION public.get_canonical_contact_info(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    office_address text,
    phone_number text,
    official_website text,
    last_updated timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target AS (
        SELECT person_id
        FROM legacy
        LIMIT 1
    ),
    spoke AS (
        SELECT ci.*
        FROM public.contact_info AS ci
        JOIN target AS t ON t.person_id = ci.person_id

        UNION

        SELECT ci.*
        FROM public.contact_info AS ci
        JOIN legacy AS l ON l.legacy_politician_id = ci.politician_id
    )
    SELECT
        ci.politician_id,
        ci.office_address,
        ci.phone_number,
        ci.official_website,
        ci.last_updated
    FROM spoke AS ci
    LEFT JOIN legacy AS l ON l.legacy_politician_id = ci.politician_id
    ORDER BY COALESCE(l.is_canonical, false) DESC,
             ci.last_updated DESC NULLS LAST,
             ci.politician_id
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_financial_disclosures(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    filing_date date,
    filing_type text,
    doc_url text,
    doc_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id, person_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target AS (
        SELECT person_id
        FROM legacy
        LIMIT 1
    ),
    spoke AS (
        SELECT fd.*
        FROM public.financial_disclosures AS fd
        JOIN target AS t ON t.person_id = fd.person_id

        UNION

        SELECT fd.*
        FROM public.financial_disclosures AS fd
        JOIN legacy AS l ON l.legacy_politician_id = fd.politician_id
    )
    SELECT
        fd.id,
        fd.filing_date,
        fd.filing_type,
        fd.doc_url,
        fd.doc_id
    FROM spoke AS fd
    ORDER BY fd.filing_date DESC, fd.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_campaign_donors(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    donation_date date,
    donor_name text,
    pac_status boolean,
    amount numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id, person_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target AS (
        SELECT person_id
        FROM legacy
        LIMIT 1
    ),
    spoke AS (
        SELECT cd.*
        FROM public.campaign_donors AS cd
        JOIN target AS t ON t.person_id = cd.person_id

        UNION

        SELECT cd.*
        FROM public.campaign_donors AS cd
        JOIN legacy AS l ON l.legacy_politician_id = cd.politician_id
    )
    SELECT
        cd.id,
        cd.donation_date,
        cd.donor_name,
        cd.pac_status,
        cd.amount
    FROM spoke AS cd
    ORDER BY cd.donation_date DESC NULLS LAST, cd.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_voting_records(
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
    roll_call_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id, person_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target AS (
        SELECT person_id
        FROM legacy
        LIMIT 1
    ),
    spoke AS (
        SELECT vr.*
        FROM public.voting_records AS vr
        JOIN target AS t ON t.person_id = vr.person_id

        UNION

        SELECT vr.*
        FROM public.voting_records AS vr
        JOIN legacy AS l ON l.legacy_politician_id = vr.politician_id
    )
    SELECT
        vr.id,
        vr.bill_name,
        vr.bill_summary,
        vr.vote_date,
        vr.vote_cast,
        vr.jurisdiction,
        vr.roll_call_id
    FROM spoke AS vr
    WHERE NULLIF(btrim(coalesce(vote_cast_filter, '')), '') IS NULL
       OR vr.vote_cast = vote_cast_filter
    ORDER BY vr.vote_date DESC, vr.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_media_mentions(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    source_api text,
    sentiment_score numeric,
    content_summary text,
    url text,
    created_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id, person_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target AS (
        SELECT person_id
        FROM legacy
        LIMIT 1
    ),
    spoke AS (
        SELECT um.*
        FROM public.unconfirmed_mentions AS um
        JOIN target AS t ON t.person_id = um.person_id

        UNION

        SELECT um.*
        FROM public.unconfirmed_mentions AS um
        JOIN legacy AS l ON l.legacy_politician_id = um.politician_id
    )
    SELECT
        um.id,
        um.source_api,
        um.sentiment_score,
        um.content_summary,
        um.url,
        um.created_at
    FROM spoke AS um
    ORDER BY um.created_at DESC NULLS LAST, um.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_shared_donors(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    shared_donor_count bigint,
    shared_total_amount numeric
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
    donor_rows AS (
        SELECT
            cd.*,
            COALESCE(cd.person_id, l.person_id) AS resolved_person_id
        FROM public.campaign_donors AS cd
        LEFT JOIN public.legacy_profile_redirects AS l
          ON l.legacy_politician_id = cd.politician_id
    ),
    mine AS (
        SELECT DISTINCT lower(btrim(dr.donor_name)) AS dn
        FROM donor_rows AS dr
        JOIN target_person AS tp ON tp.person_id = dr.resolved_person_id
        WHERE dr.donor_name IS NOT NULL
          AND btrim(dr.donor_name) <> ''
    ),
    other_donors AS (
        SELECT
            dr.resolved_person_id AS person_id,
            dr.donor_name,
            dr.amount
        FROM donor_rows AS dr
        JOIN target_person AS tp ON tp.person_id <> dr.resolved_person_id
        JOIN mine ON mine.dn = lower(btrim(dr.donor_name))
        WHERE dr.resolved_person_id IS NOT NULL
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
        FROM public.legacy_profile_redirects AS l
        JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        od.person_id AS politician_id,
        COALESCE(pe.primary_name, rh.full_name) AS full_name,
        rh.current_office,
        rh.party,
        count(DISTINCT lower(btrim(od.donor_name))) AS shared_donor_count,
        COALESCE(sum(od.amount), 0) AS shared_total_amount
    FROM other_donors AS od
    JOIN ranked_headers AS rh ON rh.person_id = od.person_id AND rh.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = od.person_id AND pe.status = 'active'
    GROUP BY od.person_id, COALESCE(pe.primary_name, rh.full_name), rh.current_office, rh.party
    ORDER BY shared_donor_count DESC, shared_total_amount DESC
    LIMIT 15;
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
    vote_rows AS (
        SELECT
            vr.*,
            COALESCE(vr.person_id, l.person_id) AS resolved_person_id
        FROM public.voting_records AS vr
        LEFT JOIN public.legacy_profile_redirects AS l
          ON l.legacy_politician_id = vr.politician_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
    ),
    mine AS (
        SELECT DISTINCT ON (vr.roll_call_id)
            vr.roll_call_id,
            vr.vote_cast
        FROM vote_rows AS vr
        JOIN target_person AS tp ON tp.person_id = vr.resolved_person_id
        ORDER BY vr.roll_call_id, vr.vote_cast
    ),
    theirs AS (
        SELECT DISTINCT ON (vr.resolved_person_id, vr.roll_call_id)
            vr.resolved_person_id AS person_id,
            vr.roll_call_id,
            vr.vote_cast
        FROM vote_rows AS vr
        JOIN target_person AS tp ON tp.person_id <> vr.resolved_person_id
        WHERE vr.resolved_person_id IS NOT NULL
        ORDER BY vr.resolved_person_id, vr.roll_call_id, vr.vote_cast
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
        FROM public.legacy_profile_redirects AS l
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

CREATE OR REPLACE FUNCTION public.get_network_ties(p_id uuid)
RETURNS TABLE (
    related_name text,
    related_politician_id uuid,
    relationship_type text,
    source_api text,
    url text
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
    tie_rows AS (
        SELECT
            r.*,
            COALESCE(r.person_id, l.person_id) AS resolved_person_id
        FROM public.relationships AS r
        LEFT JOIN public.legacy_profile_redirects AS l
          ON l.legacy_politician_id = r.politician_id
    )
    SELECT
        r.related_name,
        COALESCE(related.person_id, r.related_politician_id) AS related_politician_id,
        r.relationship_type,
        r.source_api,
        r.url
    FROM tie_rows AS r
    JOIN target_person AS tp ON tp.person_id = r.resolved_person_id
    LEFT JOIN public.legacy_profile_redirects AS related
      ON related.legacy_politician_id = r.related_politician_id
    ORDER BY (COALESCE(related.person_id, r.related_politician_id) IS NULL), r.related_name
    LIMIT 30;
$$;

CREATE OR REPLACE VIEW public.identity_validation_spoke_rows_missing_person_id AS
SELECT 'contact_info'::text AS table_name, politician_id, politician_id::text AS row_key
FROM public.contact_info
WHERE person_id IS NULL

UNION ALL

SELECT 'financial_disclosures', politician_id, id::text
FROM public.financial_disclosures
WHERE person_id IS NULL

UNION ALL

SELECT 'campaign_donors', politician_id, id::text
FROM public.campaign_donors
WHERE person_id IS NULL

UNION ALL

SELECT 'voting_records', politician_id, id::text
FROM public.voting_records
WHERE person_id IS NULL

UNION ALL

SELECT 'unconfirmed_mentions', politician_id, id::text
FROM public.unconfirmed_mentions
WHERE person_id IS NULL

UNION ALL

SELECT 'relationships', politician_id, id::text
FROM public.relationships
WHERE person_id IS NULL;

REVOKE ALL ON TABLE public.identity_validation_spoke_rows_missing_person_id
FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.get_canonical_contact_info(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_financial_disclosures(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_campaign_donors(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records(uuid, integer, integer, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_media_mentions(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_shared_donors(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_covoting(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_network_ties(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.get_canonical_contact_info(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_financial_disclosures(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_campaign_donors(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_voting_records(uuid, integer, integer, text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_media_mentions(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_shared_donors(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_covoting(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_network_ties(uuid) TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
