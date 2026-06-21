-- 0005_financial_disclosure_filings.sql
--
-- Repurposes financial_disclosures to carry FILING-LEVEL House disclosure records sourced
-- from the official House Clerk bulk feed (disclosures-clerk.house.gov). That feed exposes
-- the filing INDEX (member, filing type, date, DocID) but NOT the per-transaction asset/value
-- rows — those live only inside the linked PDF. So a row here is "member X filed disclosure Y
-- on date Z; here is the official document", not an individual trade.
--
-- The community Stock Watcher transaction feed the original asset/value/transaction columns
-- were built for is now offline (S3 403), so those columns are relaxed to NULLable and the
-- dedup key moves from (politician_id, asset_name, transaction_type, filing_date) to the
-- stable per-filing DocID.
--
-- RLS: financial_disclosures already has RLS enabled + the anon SELECT policy/grant from
-- 0004; new columns are covered automatically. Idempotent (ADD COLUMN / DROP NOT NULL /
-- CREATE INDEX IF NOT EXISTS), safe to re-run.

ALTER TABLE financial_disclosures ADD COLUMN IF NOT EXISTS doc_id TEXT;
ALTER TABLE financial_disclosures ADD COLUMN IF NOT EXISTS doc_url TEXT;
ALTER TABLE financial_disclosures ADD COLUMN IF NOT EXISTS filing_type TEXT;

-- A filing-level row has no single asset, so asset_name is no longer required.
ALTER TABLE financial_disclosures ALTER COLUMN asset_name DROP NOT NULL;

-- Stable per-filing key for idempotent upserts. A UNIQUE INDEX (not constraint) keeps this
-- re-runnable via IF NOT EXISTS; NULLs stay distinct so any legacy transaction rows that
-- predate this migration are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_financial_disclosures_doc_id
    ON financial_disclosures (doc_id);
