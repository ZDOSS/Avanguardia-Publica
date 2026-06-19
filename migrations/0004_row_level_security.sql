-- 0004_row_level_security.sql
--
-- Converges the live database to the secure-by-default Row-Level Security posture that
-- schema.sql now declares for a fresh bootstrap, and that 0003 already applied to the
-- `relationships` table.
--
-- The hub + the original spokes (politicians, contact_info, financial_disclosures,
-- campaign_donors, voting_records, unconfirmed_mentions) were created with RLS DISABLED,
-- so they were readable only because the anon role's default table privileges leave an
-- RLS-off table ungated. This makes that exposure explicit and intentional: RLS ENABLED
-- with a permissive SELECT policy + a SELECT grant for the public read roles.
--
-- Safe for the running pipeline: the scraper writes with the service-role key, which
-- BYPASSES RLS, so enabling RLS here changes nothing about ingestion. The frontend reads
-- with the anon key, which the SELECT policy + grant keep working. There are deliberately
-- NO insert/update/delete policies — all writes stay on the service-role path.
--
-- `relationships` is intentionally omitted: 0003 already set its RLS + grant. Idempotent:
-- ENABLE RLS is a no-op when already on, and DROP POLICY IF EXISTS makes the policy
-- safe to re-run.

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'politicians', 'contact_info', 'financial_disclosures', 'campaign_donors',
        'voting_records', 'unconfirmed_mentions'
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
