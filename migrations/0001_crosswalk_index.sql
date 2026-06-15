-- Migration 0001: Crosswalk index
--
-- Re-anchors the politician hub on the stable `bioguide_id` and carries the full
-- free ID crosswalk (FEC, GovTrack, OpenSecrets, Wikidata QID, etc.) sourced from
-- the @unitedstates/congress-legislators dataset. This crosswalk is what lets the
-- spoke tables be populated by ID from free government APIs instead of by fuzzy
-- name matching.
--
-- Idempotent: safe to run multiple times and safe to run against the existing DB.

-- 1. Cross-reference IDs (bioguide gets its own column already; this holds the rest:
--    fec[], govtrack, opensecrets, votesmart, wikidata, ballotpedia, icpsr, ...)
ALTER TABLE politicians
    ADD COLUMN IF NOT EXISTS external_ids JSONB NOT NULL DEFAULT '{}'::jsonb;

-- 2. Name aliases (official_full, "first last", nickname) to widen news/GDELT recall
ALTER TABLE politicians
    ADD COLUMN IF NOT EXISTS aliases TEXT[] NOT NULL DEFAULT '{}';

-- 3. Indexes ---------------------------------------------------------------------
-- Postgres does NOT auto-index foreign keys. The other spokes are covered by their
-- composite UNIQUE constraints (leftmost column is politician_id); campaign_donors
-- and the mentions ordering query are not.
CREATE INDEX IF NOT EXISTS idx_campaign_donors_politician
    ON campaign_donors (politician_id);

CREATE INDEX IF NOT EXISTS idx_unconfirmed_mentions_politician_created
    ON unconfirmed_mentions (politician_id, created_at DESC);

-- GIN index so we can resolve a politician from any crosswalk id, e.g.
--   SELECT id FROM politicians WHERE external_ids @> '{"govtrack": 300018}';
CREATE INDEX IF NOT EXISTS idx_politicians_external_ids
    ON politicians USING gin (external_ids);
