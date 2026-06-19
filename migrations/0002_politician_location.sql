-- 0002_politician_location.sql
--
-- Adds structured location to the politicians hub so the directory can filter by
-- state (and, where known, district) instead of substring-matching the free-text
-- current_office.
--
-- We deliberately store STATE + DISTRICT rather than city/zip per politician:
-- a member's office address is their DC/capitol office, not where their
-- constituents live, so a per-politician city/zip would be misleading. ZIP search
-- is resolved on the frontend (ZIP -> state) and then filtered against this
-- canonical `state` column.
--
-- `state` is the 2-letter USPS code (e.g. 'CA'); national offices (President, VP,
-- Supreme Court) leave it NULL. `district` is the House/state-legislative district
-- label where applicable (e.g. '12', 'At-Large'), otherwise NULL.

ALTER TABLE politicians ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE politicians ADD COLUMN IF NOT EXISTS district TEXT;

-- Directory filters by state, so index it.
CREATE INDEX IF NOT EXISTS idx_politicians_state ON politicians (state);
