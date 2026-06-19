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
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_politicians_state ON politicians (state);

-- 2. Verified Spoke: contact_info
CREATE TABLE IF NOT EXISTS contact_info (
    politician_id UUID PRIMARY KEY REFERENCES politicians(id) ON DELETE CASCADE,
    office_address TEXT,
    phone_number TEXT,
    official_website TEXT,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Verified Spoke: financial_disclosures
CREATE TABLE IF NOT EXISTS financial_disclosures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    asset_name TEXT NOT NULL,
    asset_value_range TEXT,
    transaction_type TEXT,
    filing_date DATE NOT NULL,
    UNIQUE(politician_id, asset_name, transaction_type, filing_date)
);

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

-- 5. Verified Spoke: voting_records
CREATE TABLE IF NOT EXISTS voting_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    bill_name TEXT NOT NULL,
    bill_summary TEXT,
    vote_cast TEXT, -- e.g., Yea, Nay, Present
    vote_date DATE NOT NULL,
    UNIQUE(politician_id, bill_name, vote_date)
);

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
