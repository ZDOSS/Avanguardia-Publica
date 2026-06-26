-- Supabase Schema for Avanguardia Publica

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. The Hub: politicians
-- bioguide_id is the stable canonical key (from @unitedstates/congress-legislators).
-- external_ids carries the rest of the free ID crosswalk (fec[], govtrack, opensecrets,
-- wikidata QID, ballotpedia, icpsr, ...) used to join spoke data from free gov APIs.
-- aliases widens name-based news matching (official_full, "first last", nickname).
CREATE TABLE IF NOT EXISTS politicians (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    full_name TEXT NOT NULL,
    current_office TEXT,
    party TEXT,
    -- 2-letter USPS state code (e.g. 'CA'); NULL for national offices (President,
    -- VP, Supreme Court). `district` is the House / state-legislative district label
    -- ('12', 'At-Large', ...) where applicable. See migrations/0002.
    state TEXT,
    district TEXT,
    -- Normalized classification for directory filters and future analytics. The scraper
    -- writes these from source metadata; migrations/0007 backfills older rows.
    government_level TEXT,
    government_branch TEXT,
    office_type TEXT,
    jurisdiction TEXT,
    bioguide_id TEXT UNIQUE,
    external_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    search_vector TSVECTOR,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_politicians_state ON politicians (state);
CREATE INDEX IF NOT EXISTS idx_politicians_government_level ON politicians (government_level);
CREATE INDEX IF NOT EXISTS idx_politicians_government_classification
    ON politicians (government_level, government_branch, office_type);
CREATE INDEX IF NOT EXISTS idx_politicians_jurisdiction ON politicians (jurisdiction);
CREATE INDEX IF NOT EXISTS idx_politicians_full_name ON politicians (full_name);
CREATE INDEX IF NOT EXISTS idx_politicians_external_ids ON politicians USING gin (external_ids);
CREATE INDEX IF NOT EXISTS idx_politicians_search_vector ON politicians USING gin (search_vector);

CREATE OR REPLACE FUNCTION update_politicians_search_vector()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector(
            'english',
            coalesce(NEW.full_name, '') || ' ' ||
            coalesce(NEW.current_office, '') || ' ' ||
            coalesce(NEW.party, '') || ' ' ||
            coalesce(NEW.government_level, '') || ' ' ||
            coalesce(NEW.government_branch, '') || ' ' ||
            coalesce(NEW.office_type, '') || ' ' ||
            coalesce(NEW.jurisdiction, '') || ' ' ||
            coalesce(array_to_string(NEW.aliases, ' '), '')
        );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS politicians_search_vector_update ON politicians;
CREATE TRIGGER politicians_search_vector_update
    BEFORE INSERT OR UPDATE OF full_name, current_office, party, aliases,
        government_level, government_branch, office_type, jurisdiction
    ON politicians
    FOR EACH ROW
    EXECUTE FUNCTION update_politicians_search_vector();

-- 2. Verified Spoke: contact_info
CREATE TABLE IF NOT EXISTS contact_info (
    politician_id UUID PRIMARY KEY REFERENCES politicians(id) ON DELETE CASCADE,
    office_address TEXT,
    phone_number TEXT,
    official_website TEXT,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Verified Spoke: financial_disclosures
-- FILING-LEVEL records from the official House Clerk bulk feed (see migrations/0005): one row
-- per disclosure document (Periodic Transaction Report / Annual), identified by the stable
-- House DocID and linked to its official PDF. The itemized asset/value/transaction rows live
-- inside that PDF, not here — the community transaction feed that populated those columns is
-- offline — so asset_name/asset_value_range/transaction_type are nullable and dedup is on
-- doc_id. (The legacy transaction columns are retained for any pre-0005 rows.)
CREATE TABLE IF NOT EXISTS financial_disclosures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    -- Filing-level metadata (House Clerk).
    doc_id TEXT,
    doc_url TEXT,
    filing_type TEXT,
    -- Legacy per-transaction columns (nullable; only set by a parsed-transaction source).
    asset_name TEXT,
    asset_value_range TEXT,
    transaction_type TEXT,
    filing_date DATE NOT NULL,
    UNIQUE(politician_id, asset_name, transaction_type, filing_date)
);

-- Stable per-filing key for idempotent upserts (NULLs stay distinct, so legacy rows are
-- unaffected). Mirrors migrations/0005.
CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_disclosures_doc_id
    ON financial_disclosures (doc_id);

CREATE INDEX IF NOT EXISTS idx_financial_disclosures_politician_filing_date
    ON financial_disclosures (politician_id, filing_date DESC, id);

-- 4. Verified Spoke: campaign_donors
CREATE TABLE IF NOT EXISTS campaign_donors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    donor_name TEXT NOT NULL,
    amount NUMERIC,
    donation_date DATE,
    pac_status BOOLEAN DEFAULT FALSE,
    fec_transaction_id TEXT UNIQUE
);

-- Serves the shared-donor cross-reference self-join (see get_shared_donors in
-- migrations/0003), which matches on a normalized donor name.
CREATE INDEX IF NOT EXISTS idx_campaign_donors_donor_name_lower
    ON campaign_donors (lower(btrim(donor_name)));

CREATE INDEX IF NOT EXISTS idx_campaign_donors_politician
    ON campaign_donors (politician_id);

CREATE INDEX IF NOT EXISTS idx_campaign_donors_politician_donation_date
    ON campaign_donors (politician_id, donation_date DESC NULLS LAST, id);

-- 5. Verified Spoke: voting_records
-- roll_call_id is a STABLE, source-namespaced id for a single roll call
-- ('openstates:<vote_event_id>' / 'govtrack:<vote_id>') shared by every legislator who
-- voted on it — it makes co-voting an exact, collision-free self-join (see
-- migrations/0003). jurisdiction is informational (state name / NULL for federal).
CREATE TABLE IF NOT EXISTS voting_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    bill_name TEXT NOT NULL,
    bill_summary TEXT,
    vote_cast TEXT, -- e.g., Yea, Nay, Present
    vote_date DATE NOT NULL,
    roll_call_id TEXT,
    jurisdiction TEXT,
    UNIQUE(politician_id, bill_name, vote_date)
);

-- Composite + covering for the co-voting self-join (see get_covoting in migrations/0003):
-- roll_call_id leads the join; politician_id + vote_cast make the dedup/aggregation index-only.
CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call
    ON voting_records (roll_call_id, politician_id, vote_cast);

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_vote_date
    ON voting_records (politician_id, vote_date DESC, id);

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_vote_cast_vote_date
    ON voting_records (politician_id, vote_cast, vote_date DESC, id);

-- 6. Third-Party Spoke: unconfirmed_mentions
CREATE TABLE IF NOT EXISTS unconfirmed_mentions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    source_api TEXT NOT NULL, -- e.g., 'LittleSis', 'WorldNews'
    content_summary TEXT NOT NULL,
    sentiment_score NUMERIC,
    url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(politician_id, source_api, url)
);

CREATE INDEX IF NOT EXISTS idx_unconfirmed_mentions_politician_created
    ON unconfirmed_mentions (politician_id, created_at DESC);

-- 7. Third-Party Spoke: relationships (structured network ties, e.g. LittleSis)
-- Powers the "Network Ties" group of the profile Connections view. related_politician_id
-- is filled only on an EXACT name match to a tracked politician (never fuzzy), enabling
-- an internal profile link; NULL for external entities. The anon-SELECT RLS policy + GRANT
-- are in the "Row-Level Security" section below; only the live RPC functions
-- (get_shared_donors / get_covoting / get_network_ties) are migration-only (see
-- migrations/0003_connections.sql) since they don't fit a table-DDL blueprint.
CREATE TABLE IF NOT EXISTS relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- NOT NULL: a tie is meaningless without its owning politician (the loader always
    -- supplies it) and it keeps the UNIQUE key below well-defined.
    politician_id UUID NOT NULL REFERENCES politicians(id) ON DELETE CASCADE,
    related_name TEXT NOT NULL,
    related_politician_id UUID REFERENCES politicians(id) ON DELETE SET NULL,
    -- NOT NULL: relationship_type is part of the UNIQUE key, and Postgres treats NULL as
    -- distinct in unique/ON CONFLICT, so a NULL would break upsert idempotency.
    relationship_type TEXT NOT NULL DEFAULT 'Connection',
    source_api TEXT NOT NULL DEFAULT 'LittleSis',
    url TEXT,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(politician_id, related_name, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_relationships_politician ON relationships (politician_id);

-- ---------------------------------------------------------------------------------------
-- Row-Level Security & grants (self-contained bootstrap)
-- ---------------------------------------------------------------------------------------
-- The frontend is read-only and talks to Supabase with the public `anon` key, so every
-- table needs RLS ENABLED with a permissive SELECT policy plus a SELECT grant for the
-- anon/authenticated roles. Writes come exclusively from the scraper's service-role key,
-- which bypasses RLS — so there are deliberately NO insert/update/delete policies.
--
-- Running this file alone now yields a fully working read-only API (the migrations remain
-- the incremental source of truth for an already-provisioned DB). Idempotent: ENABLE RLS
-- is a no-op when already on, and DROP POLICY IF EXISTS makes the policies safe to re-run.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'politicians', 'contact_info', 'financial_disclosures', 'campaign_donors',
        'voting_records', 'unconfirmed_mentions', 'relationships'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I;', t || ' read', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR SELECT TO anon, authenticated USING (true);',
            t || ' read', t
        );
        EXECUTE format('GRANT SELECT ON %I TO anon, authenticated;', t);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------------------
-- Canonical politician rollups
-- ---------------------------------------------------------------------------------------
-- Conservative read-time duplicate collapse for directory/search/profile views. Rows are
-- not merged or deleted; the read RPCs choose a canonical row only when records share a
-- normalized full name and at least two normalized official contact signals, with no
-- conflicting state/classification fields.
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
