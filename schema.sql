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
    bioguide_id TEXT UNIQUE,
    external_ids JSONB NOT NULL DEFAULT '{}'::jsonb,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector(
            'english',
            coalesce(full_name, '') || ' ' ||
            coalesce(current_office, '') || ' ' ||
            coalesce(party, '') || ' ' ||
            coalesce(array_to_string(aliases, ' '), '')
        )
    ) STORED,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_politicians_state ON politicians (state);
CREATE INDEX IF NOT EXISTS idx_politicians_full_name ON politicians (full_name);
CREATE INDEX IF NOT EXISTS idx_politicians_external_ids ON politicians USING gin (external_ids);
CREATE INDEX IF NOT EXISTS idx_politicians_search_vector ON politicians USING gin (search_vector);

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
