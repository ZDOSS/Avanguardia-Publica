-- 0016_source_catalog_backbone.sql
--
-- Phase 4 source-catalog backbone for docs/canonical_data_and_analytics_plan.md.
--
-- This is a private registry for source and endpoint review. It does not expose
-- public profile facts and does not put the scraper on a new required path.

SET statement_timeout = '30s';

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS public.source_catalog_sources (
    slug text PRIMARY KEY,
    name text NOT NULL,
    agency text,
    sub_agency text,
    branch text,
    category text NOT NULL DEFAULT 'unknown',
    source_type text NOT NULL DEFAULT 'unknown',
    access_level text NOT NULL DEFAULT 'unknown',
    auth_type text NOT NULL DEFAULT 'unknown',
    credential_provider text,
    base_url text,
    docs_url text,
    formats text[] NOT NULL DEFAULT ARRAY[]::text[],
    coverage text,
    update_cadence text,
    priority text NOT NULL DEFAULT 'unknown',
    status text NOT NULL DEFAULT 'candidate',
    verified_lane text NOT NULL DEFAULT 'not_applicable',
    repo_fit text NOT NULL DEFAULT 'candidate',
    verified_at date,
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.source_catalog_endpoints (
    source_slug text NOT NULL REFERENCES public.source_catalog_sources(slug) ON DELETE CASCADE,
    endpoint_slug text NOT NULL,
    display_name text NOT NULL,
    endpoint_type text NOT NULL DEFAULT 'api',
    url text NOT NULL,
    docs_url text,
    formats text[] NOT NULL DEFAULT ARRAY[]::text[],
    access_level text NOT NULL DEFAULT 'unknown',
    auth_type text NOT NULL DEFAULT 'unknown',
    credential_provider text,
    update_cadence text,
    status text NOT NULL DEFAULT 'candidate',
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_slug, endpoint_slug)
);

CREATE TABLE IF NOT EXISTS public.source_catalog_source_system_links (
    source_slug text NOT NULL REFERENCES public.source_catalog_sources(slug) ON DELETE CASCADE,
    source_system_key text NOT NULL REFERENCES public.source_systems(key) ON DELETE RESTRICT,
    link_type text NOT NULL DEFAULT 'same_source',
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_slug, source_system_key, link_type)
);

CREATE TABLE IF NOT EXISTS public.source_catalog_review_events (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_slug text NOT NULL REFERENCES public.source_catalog_sources(slug) ON DELETE CASCADE,
    endpoint_slug text,
    previous_status text,
    new_status text NOT NULL,
    reviewer text,
    reviewed_at timestamptz NOT NULL DEFAULT now(),
    reason text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (source_slug, endpoint_slug)
        REFERENCES public.source_catalog_endpoints(source_slug, endpoint_slug)
        ON DELETE CASCADE
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_status_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_status_check
            CHECK (status IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_priority_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_priority_check
            CHECK (priority IN ('P0', 'P1', 'P2', 'P3', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_verified_lane_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_verified_lane_check
            CHECK (verified_lane IN ('verified', 'unverified', 'mixed', 'not_applicable'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_source_type_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_source_type_check
            CHECK (source_type IN ('api', 'bulk_data', 'feed', 'repository', 'website', 'manual_seed', 'aggregator', 'directory', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_access_level_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_access_level_check
            CHECK (access_level IN ('open', 'free_key', 'free_tier', 'restricted', 'paid', 'internal', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_auth_type_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_auth_type_check
            CHECK (auth_type IN ('none', 'api_key', 'oauth', 'download', 'manual', 'internal', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_sources_repo_fit_check'
          AND conrelid = 'public.source_catalog_sources'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_sources
            ADD CONSTRAINT source_catalog_sources_repo_fit_check
            CHECK (repo_fit IN ('wired', 'candidate', 'deferred', 'blocked', 'duplicate', 'retired', 'needs_review'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_endpoints_status_check'
          AND conrelid = 'public.source_catalog_endpoints'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_endpoints
            ADD CONSTRAINT source_catalog_endpoints_status_check
            CHECK (status IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_endpoints_endpoint_type_check'
          AND conrelid = 'public.source_catalog_endpoints'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_endpoints
            ADD CONSTRAINT source_catalog_endpoints_endpoint_type_check
            CHECK (endpoint_type IN ('api', 'bulk_file', 'feed', 'repository', 'website', 'documentation', 'directory', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_endpoints_access_level_check'
          AND conrelid = 'public.source_catalog_endpoints'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_endpoints
            ADD CONSTRAINT source_catalog_endpoints_access_level_check
            CHECK (access_level IN ('open', 'free_key', 'free_tier', 'restricted', 'paid', 'internal', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_endpoints_auth_type_check'
          AND conrelid = 'public.source_catalog_endpoints'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_endpoints
            ADD CONSTRAINT source_catalog_endpoints_auth_type_check
            CHECK (auth_type IN ('none', 'api_key', 'oauth', 'download', 'manual', 'internal', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_source_system_links_type_check'
          AND conrelid = 'public.source_catalog_source_system_links'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_source_system_links
            ADD CONSTRAINT source_catalog_source_system_links_type_check
            CHECK (link_type IN ('same_source', 'identifier_source', 'data_provider', 'credential_provider', 'aggregation_member'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_review_events_previous_status_check'
          AND conrelid = 'public.source_catalog_review_events'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_review_events
            ADD CONSTRAINT source_catalog_review_events_previous_status_check
            CHECK (previous_status IS NULL OR previous_status IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'source_catalog_review_events_new_status_check'
          AND conrelid = 'public.source_catalog_review_events'::regclass
    ) THEN
        ALTER TABLE public.source_catalog_review_events
            ADD CONSTRAINT source_catalog_review_events_new_status_check
            CHECK (new_status IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_catalog_sources_status
    ON public.source_catalog_sources(status, priority, category);
CREATE INDEX IF NOT EXISTS idx_source_catalog_sources_repo_fit
    ON public.source_catalog_sources(repo_fit, status);
CREATE INDEX IF NOT EXISTS idx_source_catalog_sources_base_url
    ON public.source_catalog_sources(base_url)
    WHERE base_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_catalog_endpoints_status
    ON public.source_catalog_endpoints(status, endpoint_type);
CREATE INDEX IF NOT EXISTS idx_source_catalog_endpoints_url
    ON public.source_catalog_endpoints(url);
CREATE INDEX IF NOT EXISTS idx_source_catalog_links_source_system
    ON public.source_catalog_source_system_links(source_system_key);
CREATE INDEX IF NOT EXISTS idx_source_catalog_review_events_source
    ON public.source_catalog_review_events(source_slug, reviewed_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_catalog_review_events_endpoint
    ON public.source_catalog_review_events(source_slug, endpoint_slug, reviewed_at DESC)
    WHERE endpoint_slug IS NOT NULL;

DROP TRIGGER IF EXISTS source_catalog_sources_set_updated_at ON public.source_catalog_sources;
CREATE TRIGGER source_catalog_sources_set_updated_at
    BEFORE UPDATE ON public.source_catalog_sources
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS source_catalog_endpoints_set_updated_at ON public.source_catalog_endpoints;
CREATE TRIGGER source_catalog_endpoints_set_updated_at
    BEFORE UPDATE ON public.source_catalog_endpoints
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS source_catalog_source_system_links_set_updated_at ON public.source_catalog_source_system_links;
CREATE TRIGGER source_catalog_source_system_links_set_updated_at
    BEFORE UPDATE ON public.source_catalog_source_system_links
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS source_catalog_review_events_set_updated_at ON public.source_catalog_review_events;
CREATE TRIGGER source_catalog_review_events_set_updated_at
    BEFORE UPDATE ON public.source_catalog_review_events
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

INSERT INTO public.source_catalog_sources (
    slug,
    name,
    agency,
    branch,
    category,
    source_type,
    access_level,
    auth_type,
    credential_provider,
    base_url,
    docs_url,
    formats,
    coverage,
    update_cadence,
    priority,
    status,
    verified_lane,
    repo_fit,
    notes
) VALUES
    ('avanguardia-legacy-profile', 'Avanguardia legacy politician profile', 'Avanguardia Publica', 'internal', 'identity', 'manual_seed', 'internal', 'internal', NULL, NULL, NULL, ARRAY[]::text[], 'Legacy politicians.id profile UUIDs preserved for redirects.', 'internal', 'P0', 'approved', 'not_applicable', 'wired', 'Internal compatibility source; not a public data source.'),
    ('bioguide', 'Biographical Directory of the United States Congress', 'U.S. Congress', 'legislative', 'identity', 'website', 'open', 'none', NULL, 'https://bioguide.congress.gov/', 'https://bioguide.congress.gov/', ARRAY['html']::text[], 'Official congressional biography and Bioguide identifiers.', 'ongoing', 'P0', 'approved', 'verified', 'wired', 'Currently used as a trusted identifier, mostly through congress-legislators crosswalk data.'),
    ('congress-legislators', 'unitedstates/congress-legislators', 'Community-maintained public data', 'legislative', 'identity_and_roles', 'repository', 'open', 'none', NULL, 'https://github.com/unitedstates/congress-legislators', 'https://github.com/unitedstates/congress-legislators', ARRAY['yaml', 'json', 'csv']::text[], 'Congressional rosters, contact data, aliases, and crosswalk identifiers.', 'community maintained', 'P0', 'approved', 'mixed', 'wired', 'Trusted open-data source currently used by the federal roster path.'),
    ('openstates', 'OpenStates', 'OpenStates', 'state_legislative', 'identity_roles_and_votes', 'repository', 'open', 'none', NULL, 'https://github.com/openstates/people', 'https://docs.openstates.org/', ARRAY['yaml', 'json']::text[], 'State legislators, governors, and state legislative vote data.', 'community maintained', 'P0', 'approved', 'mixed', 'wired', 'People YAML is keyless; OpenStates API v3 is used for state votes.'),
    ('govtrack', 'GovTrack', 'GovTrack.us', 'legislative', 'federal_votes', 'api', 'open', 'none', NULL, 'https://www.govtrack.us/api/v2', 'https://www.govtrack.us/developers/api', ARRAY['json']::text[], 'Federal voting records joined by GovTrack person ID.', 'ongoing', 'P0', 'approved', 'mixed', 'wired', 'Used as a federal voting source until official roll-call endpoints replace or reconcile it.'),
    ('openfec', 'OpenFEC API', 'Federal Election Commission', 'campaign_finance', 'campaign_finance', 'api', 'free_key', 'api_key', 'api.data.gov', 'https://api.open.fec.gov/v1', 'https://api.open.fec.gov/developers/', ARRAY['json']::text[], 'Official FEC campaign finance records and candidate/committee endpoints.', 'ongoing', 'P0', 'approved', 'verified', 'wired', 'Current scraper uses bounded itemized receipts via a free api.data.gov key.'),
    ('wikidata', 'Wikidata', 'Wikimedia Foundation', 'crosswalk', 'identity_crosswalk', 'website', 'open', 'none', NULL, 'https://www.wikidata.org/', 'https://www.wikidata.org/wiki/Wikidata:Data_access', ARRAY['json', 'rdf']::text[], 'QID crosswalks for federal executive and Supreme Court seed data.', 'ongoing', 'P1', 'approved', 'mixed', 'wired', 'Trusted only when the QID is sourced from a curated seed or crosswalk.'),
    ('fjc', 'Federal Judicial Center', 'Federal Judicial Center', 'judicial', 'identity', 'website', 'open', 'none', NULL, 'https://www.fjc.gov/history/judges', 'https://www.fjc.gov/history/judges', ARRAY['html']::text[], 'Federal judge biography identifiers reserved for judicial sources.', 'ongoing', 'P1', 'approved', 'verified', 'wired', 'Reserved identity source; broader judicial ingestion is not implemented yet.'),
    ('house-clerk', 'U.S. House Clerk financial disclosures', 'U.S. House Clerk', 'legislative', 'financial_disclosures', 'bulk_data', 'open', 'download', NULL, 'https://disclosures-clerk.house.gov/public_disc/', 'https://disclosures-clerk.house.gov/FinancialDisclosure', ARRAY['zip', 'txt', 'pdf']::text[], 'Official House financial disclosure filing index and PDFs.', 'annual', 'P0', 'approved', 'verified', 'wired', 'Current loader stores filing-level records only; no asset-level parsing yet.'),
    ('littlesis', 'LittleSis', 'LittleSis', 'third_party', 'relationships', 'api', 'open', 'none', NULL, 'https://littlesis.org', 'https://littlesis.org/api', ARRAY['json']::text[], 'Third-party relationship and mention data.', 'ongoing', 'P2', 'approved', 'unverified', 'wired', 'Unverified network source; never a deterministic identity join.'),
    ('news-aggregator', 'News aggregator pipeline', 'Avanguardia Publica', 'third_party', 'media_mentions', 'aggregator', 'internal', 'internal', NULL, NULL, NULL, ARRAY[]::text[], 'Internal multi-tier media mention pipeline.', 'per ETL run', 'P2', 'approved', 'unverified', 'wired', 'Routes through provider-specific sources and GDELT fallback.'),
    ('currents', 'Currents API', 'Currents API', 'third_party', 'media_mentions', 'api', 'free_tier', 'api_key', 'currents', 'https://api.currentsapi.services/v1/search', 'https://currentsapi.services/en/docs/', ARRAY['json']::text[], 'Free-tier news search provider.', 'ongoing', 'P2', 'approved', 'unverified', 'wired', 'Unverified media source in the news aggregator tier.'),
    ('newsdata', 'NewsData.io', 'NewsData.io', 'third_party', 'media_mentions', 'api', 'free_tier', 'api_key', 'newsdata', 'https://newsdata.io/api/1/news', 'https://newsdata.io/documentation', ARRAY['json']::text[], 'Free-tier news search provider.', 'ongoing', 'P2', 'approved', 'unverified', 'wired', 'Unverified media source in the news aggregator tier.'),
    ('thenewsapi', 'TheNewsAPI', 'TheNewsAPI', 'third_party', 'media_mentions', 'api', 'free_tier', 'api_key', 'thenewsapi', 'https://api.thenewsapi.com/v1/news/all', 'https://www.thenewsapi.com/documentation', ARRAY['json']::text[], 'Free-tier news search provider.', 'ongoing', 'P2', 'approved', 'unverified', 'wired', 'Unverified media source in the news aggregator tier.'),
    ('gdelt', 'GDELT', 'GDELT Project', 'open_data', 'media_mentions', 'feed', 'open', 'none', NULL, 'https://data.gdeltproject.org/gdeltv2/', 'https://www.gdeltproject.org/data.html', ARRAY['txt', 'tsv', 'zip']::text[], 'Open-data media fallback source.', 'near real-time', 'P2', 'approved', 'unverified', 'wired', 'Keyless fallback used by the news aggregator.')
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    agency = EXCLUDED.agency,
    branch = EXCLUDED.branch,
    category = EXCLUDED.category,
    source_type = EXCLUDED.source_type,
    access_level = EXCLUDED.access_level,
    auth_type = EXCLUDED.auth_type,
    credential_provider = EXCLUDED.credential_provider,
    base_url = EXCLUDED.base_url,
    docs_url = EXCLUDED.docs_url,
    formats = EXCLUDED.formats,
    coverage = EXCLUDED.coverage,
    update_cadence = EXCLUDED.update_cadence,
    priority = EXCLUDED.priority,
    status = EXCLUDED.status,
    verified_lane = EXCLUDED.verified_lane,
    repo_fit = EXCLUDED.repo_fit,
    notes = EXCLUDED.notes;

INSERT INTO public.source_catalog_endpoints (
    source_slug,
    endpoint_slug,
    display_name,
    endpoint_type,
    url,
    docs_url,
    formats,
    access_level,
    auth_type,
    credential_provider,
    update_cadence,
    status,
    notes
) VALUES
    ('bioguide', 'bioguide-web', 'Bioguide web directory', 'website', 'https://bioguide.congress.gov/', 'https://bioguide.congress.gov/', ARRAY['html']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Official congressional biography surface.'),
    ('congress-legislators', 'repository', 'congress-legislators repository', 'repository', 'https://github.com/unitedstates/congress-legislators', 'https://github.com/unitedstates/congress-legislators', ARRAY['yaml', 'json', 'csv']::text[], 'open', 'none', NULL, 'community maintained', 'approved', 'Current federal roster and crosswalk source.'),
    ('openstates', 'people-tarball', 'OpenStates people tarball', 'bulk_file', 'https://github.com/openstates/people/archive/refs/heads/main.tar.gz', 'https://github.com/openstates/people', ARRAY['yaml', 'tar.gz']::text[], 'open', 'none', NULL, 'community maintained', 'approved', 'Current state official identity source.'),
    ('openstates', 'api-v3', 'OpenStates API v3', 'api', 'https://v3.openstates.org', 'https://docs.openstates.org/api-v3/', ARRAY['json']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Current state roll-call vote source.'),
    ('govtrack', 'api-v2', 'GovTrack API v2', 'api', 'https://www.govtrack.us/api/v2', 'https://www.govtrack.us/developers/api', ARRAY['json']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Current federal vote source.'),
    ('openfec', 'api-v1', 'OpenFEC API v1', 'api', 'https://api.open.fec.gov/v1', 'https://api.open.fec.gov/developers/', ARRAY['json']::text[], 'free_key', 'api_key', 'api.data.gov', 'ongoing', 'approved', 'Current campaign donor source.'),
    ('wikidata', 'entity-data', 'Wikidata entity data', 'api', 'https://www.wikidata.org/wiki/Special:EntityData/', 'https://www.wikidata.org/wiki/Wikidata:Data_access', ARRAY['json', 'rdf']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Used only through curated seeds or trusted crosswalks.'),
    ('fjc', 'judges-directory', 'FJC judges directory', 'website', 'https://www.fjc.gov/history/judges', 'https://www.fjc.gov/history/judges', ARRAY['html']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Reserved for future judicial identity ingestion.'),
    ('house-clerk', 'financial-disclosure-bulk', 'House financial disclosure bulk files', 'bulk_file', 'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/', 'https://disclosures-clerk.house.gov/FinancialDisclosure', ARRAY['zip', 'txt', 'pdf']::text[], 'open', 'download', NULL, 'annual', 'approved', 'Current House filing-index source.'),
    ('littlesis', 'api', 'LittleSis API', 'api', 'https://littlesis.org', 'https://littlesis.org/api', ARRAY['json']::text[], 'open', 'none', NULL, 'ongoing', 'approved', 'Unverified relationship source.'),
    ('currents', 'search', 'Currents search API', 'api', 'https://api.currentsapi.services/v1/search', 'https://currentsapi.services/en/docs/', ARRAY['json']::text[], 'free_tier', 'api_key', 'currents', 'ongoing', 'approved', 'Unverified news provider.'),
    ('newsdata', 'news', 'NewsData.io news API', 'api', 'https://newsdata.io/api/1/news', 'https://newsdata.io/documentation', ARRAY['json']::text[], 'free_tier', 'api_key', 'newsdata', 'ongoing', 'approved', 'Unverified news provider.'),
    ('thenewsapi', 'all-news', 'TheNewsAPI all news endpoint', 'api', 'https://api.thenewsapi.com/v1/news/all', 'https://www.thenewsapi.com/documentation', ARRAY['json']::text[], 'free_tier', 'api_key', 'thenewsapi', 'ongoing', 'approved', 'Unverified news provider.'),
    ('gdelt', 'lastupdate', 'GDELT GKG lastupdate feed', 'feed', 'https://data.gdeltproject.org/gdeltv2/lastupdate.txt', 'https://www.gdeltproject.org/data.html', ARRAY['txt', 'tsv', 'zip']::text[], 'open', 'none', NULL, 'near real-time', 'approved', 'Keyless GKG fallback feed.')
ON CONFLICT (source_slug, endpoint_slug) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    endpoint_type = EXCLUDED.endpoint_type,
    url = EXCLUDED.url,
    docs_url = EXCLUDED.docs_url,
    formats = EXCLUDED.formats,
    access_level = EXCLUDED.access_level,
    auth_type = EXCLUDED.auth_type,
    credential_provider = EXCLUDED.credential_provider,
    update_cadence = EXCLUDED.update_cadence,
    status = EXCLUDED.status,
    notes = EXCLUDED.notes;

INSERT INTO public.source_catalog_source_system_links (
    source_slug,
    source_system_key,
    link_type,
    notes
) VALUES
    ('avanguardia-legacy-profile', 'avanguardia-legacy-profile', 'same_source', 'Internal legacy profile identity source.'),
    ('bioguide', 'bioguide', 'same_source', 'Official congressional person identifier.'),
    ('congress-legislators', 'congress-legislators', 'same_source', 'Roster and crosswalk source.'),
    ('openstates', 'openstates', 'same_source', 'OpenStates person and vote source.'),
    ('govtrack', 'govtrack', 'same_source', 'GovTrack person ID and vote source.'),
    ('openfec', 'fec', 'data_provider', 'FEC candidate IDs and campaign finance data.'),
    ('openfec', 'openfec', 'same_source', 'OpenFEC API source alias.'),
    ('wikidata', 'wikidata', 'same_source', 'Trusted crosswalk source only when curated.'),
    ('fjc', 'fjc', 'same_source', 'Federal Judicial Center identifier source.'),
    ('house-clerk', 'house-clerk', 'same_source', 'House financial disclosure source.'),
    ('littlesis', 'littlesis', 'same_source', 'Unverified network source.'),
    ('news-aggregator', 'news-aggregator', 'same_source', 'Internal aggregate media pipeline source.'),
    ('currents', 'currents', 'aggregation_member', 'News aggregator provider.'),
    ('newsdata', 'newsdata', 'aggregation_member', 'News aggregator provider.'),
    ('thenewsapi', 'thenewsapi', 'aggregation_member', 'News aggregator provider.'),
    ('gdelt', 'gdelt', 'aggregation_member', 'News aggregator fallback provider.')
ON CONFLICT (source_slug, source_system_key, link_type) DO UPDATE SET
    notes = EXCLUDED.notes;

CREATE OR REPLACE VIEW public.source_catalog_validation_pending_review AS
SELECT
    slug,
    name,
    category,
    priority,
    status,
    repo_fit,
    notes,
    updated_at
FROM public.source_catalog_sources
WHERE status IN ('candidate', 'deferred', 'blocked')
   OR repo_fit IN ('candidate', 'needs_review', 'deferred', 'blocked');

CREATE OR REPLACE VIEW public.source_catalog_validation_unlinked_source_systems AS
SELECT
    ss.key AS source_system_key,
    ss.display_name,
    ss.source_kind,
    ss.trust_level,
    ss.verified
FROM public.source_systems AS ss
LEFT JOIN public.source_catalog_source_system_links AS link
  ON link.source_system_key = ss.key
WHERE link.source_system_key IS NULL;

CREATE OR REPLACE VIEW public.source_catalog_validation_duplicate_endpoint_urls AS
SELECT
    url,
    count(*) AS endpoint_count,
    array_agg(source_slug || ':' || endpoint_slug ORDER BY source_slug, endpoint_slug) AS endpoints
FROM public.source_catalog_endpoints
GROUP BY url
HAVING count(*) > 1;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'source_catalog_sources',
        'source_catalog_endpoints',
        'source_catalog_source_system_links',
        'source_catalog_review_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated;', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO service_role;', t);
    END LOOP;
END $$;

REVOKE ALL ON TABLE public.source_catalog_validation_pending_review FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_validation_unlinked_source_systems FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_validation_duplicate_endpoint_urls FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE public.source_catalog_validation_pending_review TO service_role;
GRANT SELECT ON TABLE public.source_catalog_validation_unlinked_source_systems TO service_role;
GRANT SELECT ON TABLE public.source_catalog_validation_duplicate_endpoint_urls TO service_role;

NOTIFY pgrst, 'reload schema';
