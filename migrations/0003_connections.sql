-- 0003_connections.sql
--
-- Adds the data + read-only query API behind the profile "Connections" view, which
-- cross-references individuals using the spokes we already ingest:
--
--   * Shared donors   — campaign_donors joined on the donor name.
--   * Co-voting        — voting_records joined on a STABLE per-roll-call id.
--   * Network ties     — LittleSis structured relationships (unverified lane).
--
-- All connections are computed LIVE, on demand, by the RPC functions at the bottom of
-- this file (called client-side via supabase.rpc) — there is no precomputed table and
-- no nightly job. See docs/connections_design.md.
--
-- Idempotent (ADD COLUMN / CREATE INDEX / CREATE OR REPLACE ... IF NOT EXISTS), so it
-- is safe to re-run, matching 0002.

-- 1. Precise co-voting key ----------------------------------------------------------
-- voting_records previously held only (bill_name, vote_date). bill_name like
-- "HB 1 — Final Passage" repeats across all 50 states, so a (bill_name, vote_date)
-- self-join would wrongly match Texas's HB 1 to Florida's HB 1. roll_call_id is a
-- source-namespaced id for a single roll call (e.g. 'openstates:ocd-vote/...',
-- 'govtrack:123'); EVERY legislator who voted on that roll call shares it, so
-- co-voting becomes an exact, collision-free self-join. jurisdiction is informational
-- (the state name for state votes; NULL for federal GovTrack votes).
-- Both nullable: existing rows backfill to NULL and simply don't participate in
-- co-voting until re-scraped. The (politician_id, bill_name, vote_date) UNIQUE key is
-- unchanged, so upserts stay idempotent.
ALTER TABLE voting_records ADD COLUMN IF NOT EXISTS roll_call_id TEXT;
ALTER TABLE voting_records ADD COLUMN IF NOT EXISTS jurisdiction TEXT;
CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call ON voting_records (roll_call_id);

-- 2. Shared-donor lookup index ------------------------------------------------------
-- The shared-donor self-join matches on a normalized donor name; index the same
-- expression so the per-profile lookup stays cheap.
CREATE INDEX IF NOT EXISTS idx_campaign_donors_donor_name_lower
    ON campaign_donors (lower(btrim(donor_name)));

-- 3. Network ties: structured relationships (third-party / unverified lane) ----------
-- Structured edges from LittleSis (board memberships, affiliations, ...). related_name
-- is the other entity as the source names it; related_politician_id is filled ONLY
-- when that name is an EXACT match to a politician we already track (never fuzzy — see
-- loader.py's identity rule), enabling an internal profile link. NULL otherwise (an
-- external entity we just name + link out to).
CREATE TABLE IF NOT EXISTS relationships (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    politician_id UUID REFERENCES politicians(id) ON DELETE CASCADE,
    related_name TEXT NOT NULL,
    related_politician_id UUID REFERENCES politicians(id) ON DELETE SET NULL,
    -- NOT NULL (default 'Connection') is load-bearing: relationship_type is part of the
    -- UNIQUE key below, and under Postgres NULL <> NULL, so a NULL here would defeat the
    -- ON CONFLICT upsert and insert a duplicate every nightly run. The extractor always
    -- supplies a value, so the default is just a safety net.
    relationship_type TEXT NOT NULL DEFAULT 'Connection',
    source_api TEXT NOT NULL DEFAULT 'LittleSis',
    url TEXT,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(politician_id, related_name, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_relationships_politician ON relationships (politician_id);

-- Mirror the read-only public exposure the existing spokes rely on: the browser uses
-- the anon key, so it must be able to SELECT this table. Writes come from the scraper's
-- service-role key, which bypasses RLS.
ALTER TABLE relationships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "relationships read" ON relationships;
CREATE POLICY "relationships read" ON relationships
    FOR SELECT TO anon, authenticated USING (true);
GRANT SELECT ON relationships TO anon, authenticated;

-- 4. The live "Connections" API: RPC functions --------------------------------------
-- All STABLE + SECURITY DEFINER (read-only aggregation over the spokes), bounded by a
-- LIMIT, and EXECUTE-granted to the anon role so the static frontend can call them
-- directly with supabase.rpc(). search_path is pinned per the SECURITY DEFINER
-- hardening guidance.

-- 4a. Shared donors: other politicians funded by the same donor(s) as p_id.
CREATE OR REPLACE FUNCTION get_shared_donors(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    shared_donor_count bigint,
    shared_total_amount numeric
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    WITH mine AS (
        SELECT DISTINCT lower(btrim(donor_name)) AS dn
        FROM campaign_donors
        WHERE politician_id = p_id AND donor_name IS NOT NULL AND btrim(donor_name) <> ''
    )
    SELECT p.id, p.full_name, p.current_office, p.party,
           COUNT(DISTINCT lower(btrim(cd.donor_name))) AS shared_donor_count,
           COALESCE(SUM(cd.amount), 0) AS shared_total_amount
    FROM campaign_donors cd
    JOIN mine ON lower(btrim(cd.donor_name)) = mine.dn
    JOIN politicians p ON p.id = cd.politician_id
    WHERE cd.politician_id <> p_id
    GROUP BY p.id, p.full_name, p.current_office, p.party
    ORDER BY shared_donor_count DESC, shared_total_amount DESC
    LIMIT 15;
$$;

-- 4b. Co-voting: who voted with / against p_id on the same roll calls. Returns a
-- single ranked set (most shared roll calls first); the client buckets into allies
-- (high agreement_rate) and opponents (low) for display.
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
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    WITH mine AS (
        SELECT roll_call_id, vote_cast
        FROM voting_records
        WHERE politician_id = p_id AND roll_call_id IS NOT NULL
    )
    SELECT p.id, p.full_name, p.current_office, p.party,
           COUNT(*) FILTER (WHERE vr.vote_cast = mine.vote_cast) AS agree_count,
           COUNT(*) FILTER (WHERE vr.vote_cast <> mine.vote_cast) AS disagree_count,
           COUNT(*) AS shared_total,
           ROUND(
               COUNT(*) FILTER (WHERE vr.vote_cast = mine.vote_cast)::numeric
               / NULLIF(COUNT(*), 0), 3
           ) AS agreement_rate
    FROM voting_records vr
    JOIN mine ON mine.roll_call_id = vr.roll_call_id
    JOIN politicians p ON p.id = vr.politician_id
    WHERE vr.politician_id <> p_id AND vr.roll_call_id IS NOT NULL
    GROUP BY p.id, p.full_name, p.current_office, p.party
    ORDER BY shared_total DESC, agreement_rate DESC
    LIMIT 30;
$$;

-- 4c. Network ties: LittleSis structured relationships for p_id. Internal-linked
-- relations (related_politician_id NOT NULL) are surfaced first.
CREATE OR REPLACE FUNCTION get_network_ties(p_id uuid)
RETURNS TABLE (
    related_name text,
    related_politician_id uuid,
    relationship_type text,
    source_api text,
    url text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT related_name, related_politician_id, relationship_type, source_api, url
    FROM relationships
    WHERE politician_id = p_id
    ORDER BY (related_politician_id IS NULL), related_name
    LIMIT 30;
$$;

GRANT EXECUTE ON FUNCTION get_shared_donors(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_covoting(uuid)      TO anon, authenticated;
GRANT EXECUTE ON FUNCTION get_network_ties(uuid)  TO anon, authenticated;
