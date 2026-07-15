-- 0023_source_inventory_context_seed.sql
--
-- Seed the remaining roadmap-listed FCC/GSA jurisdiction and official-domain
-- context sources as private review candidates. This migration does not add an
-- extractor, source quotas, public facts, or credentials.
--
-- The applied marker makes the scraper refuse to run against a catalog that has
-- not received this forward-only review batch.

BEGIN;

SET LOCAL statement_timeout = '30s';

INSERT INTO public.source_catalog_sources (
    slug,
    name,
    agency,
    sub_agency,
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
    verified_at,
    notes,
    metadata
) VALUES
    (
        'fcc-area-api',
        'FCC Area API',
        'Federal Communications Commission',
        NULL,
        'independent',
        'jurisdiction_lookup',
        'api',
        'open',
        'none',
        NULL,
        'https://geo.fcc.gov/api/census/',
        'https://geo.fcc.gov/api/census/',
        ARRAY['json', 'xml']::text[],
        'Census block, county, state, and market-area context from latitude/longitude, including block FIPS lookup.',
        'Census-vintage dependent',
        'P1',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-15',
        'Official coordinate-to-geography context candidate. Review API terms, coordinate-input provenance, Census vintage, retention, and request limits before any context-only ingestion path; never use it to infer person identity.',
        jsonb_build_object(
            'inventory_file', 'canonical_data_and_analytics_plan',
            'inventory_slug', 'fcc-area-census-block-api',
            'inventory_status', 'Verified public docs',
            'official_docs_checked_at', '2026-07-15',
            'repo_usage_status', 'Not wired; roadmap-listed official context candidate',
            'repo_evidence', 'No FCC Area API extractor is present in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Review terms, Census vintage, coordinate provenance, retention, and request limits before adding a context-only source-record path.',
            'source_url', 'https://geo.fcc.gov/api/census/'
        )
    ),
    (
        'gsa-site-scanning-api',
        'GSA Site Scanning API',
        'General Services Administration',
        'Open Technology',
        'executive',
        'official_domain_context',
        'api',
        'free_key',
        'api_key',
        'api.data.gov',
        'https://api.gsa.gov/technology/site-scanning/v1/',
        'https://open.gsa.gov/api/site-scanning-api/',
        ARRAY['json', 'csv']::text[],
        'Daily scans and metadata for U.S. federal government websites, including official-domain and agency-owner context.',
        'daily',
        'P2',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-15',
        'Official-domain context candidate. The API requires an api.data.gov key; do not ingest or expose scan findings until a maintainer reviews data minimization, retention, redistribution, attribution, and quota behavior.',
        jsonb_build_object(
            'inventory_file', 'canonical_data_and_analytics_plan',
            'inventory_slug', 'gsa-site-scanning-api',
            'inventory_status', 'Verified public docs',
            'official_docs_checked_at', '2026-07-15',
            'repo_usage_status', 'Not wired; roadmap-listed official domain-context candidate',
            'repo_evidence', 'No GSA Site Scanning extractor is present in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Review api.data.gov quota, data minimization, retention, redistribution, attribution, and domain-verification use before adding a context-only source-record path.',
            'source_url', 'https://open.gsa.gov/api/site-scanning-api/'
        )
    )
ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    agency = EXCLUDED.agency,
    sub_agency = EXCLUDED.sub_agency,
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
    status = public.source_catalog_sources.status,
    verified_lane = EXCLUDED.verified_lane,
    repo_fit = public.source_catalog_sources.repo_fit,
    verified_at = EXCLUDED.verified_at,
    notes = CASE
        WHEN NULLIF(btrim(public.source_catalog_sources.notes), '') IS NULL THEN EXCLUDED.notes
        ELSE public.source_catalog_sources.notes
    END,
    metadata = public.source_catalog_sources.metadata || EXCLUDED.metadata;

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
    notes,
    metadata
) VALUES
    (
        'fcc-area-api',
        'area',
        'FCC Area API /area',
        'api',
        'https://geo.fcc.gov/api/census/area',
        'https://geo.fcc.gov/api/census/',
        ARRAY['json', 'xml']::text[],
        'open',
        'none',
        NULL,
        'Census-vintage dependent',
        'candidate',
        'Returns Census block, county, state, and market-area context from latitude/longitude.',
        jsonb_build_object('inventory_file', 'canonical_data_and_analytics_plan', 'inventory_slug', 'fcc-area-census-block-api')
    ),
    (
        'fcc-area-api',
        'block-find',
        'FCC Block API /block/find',
        'api',
        'https://geo.fcc.gov/api/census/block/find',
        'https://geo.fcc.gov/api/census/',
        ARRAY['json', 'xml']::text[],
        'open',
        'none',
        NULL,
        'Census-vintage dependent',
        'candidate',
        'Returns Census block, county, and state FIPS context from latitude/longitude.',
        jsonb_build_object('inventory_file', 'canonical_data_and_analytics_plan', 'inventory_slug', 'fcc-area-census-block-api')
    ),
    (
        'gsa-site-scanning-api',
        'websites-v1',
        'GSA Site Scanning API v1 websites',
        'api',
        'https://api.gsa.gov/technology/site-scanning/v1/websites',
        'https://open.gsa.gov/api/site-scanning-api/',
        ARRAY['json']::text[],
        'free_key',
        'api_key',
        'api.data.gov',
        'daily',
        'candidate',
        'Paginated scan metadata for targeted federal websites; requires an api.data.gov key in the x-api-key header.',
        jsonb_build_object('inventory_file', 'canonical_data_and_analytics_plan', 'inventory_slug', 'gsa-site-scanning-api')
    )
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
    status = public.source_catalog_endpoints.status,
    notes = CASE
        WHEN NULLIF(btrim(public.source_catalog_endpoints.notes), '') IS NULL THEN EXCLUDED.notes
        ELSE public.source_catalog_endpoints.notes
    END,
    metadata = public.source_catalog_endpoints.metadata || EXCLUDED.metadata;

WITH review_seed(source_slug, previous_status, new_status, reason, evidence) AS (
    VALUES
        (
            'fcc-area-api',
            NULL,
            'candidate',
            'Seeded from the roadmap-listed FCC jurisdiction/context source for maintainer review.',
            jsonb_build_object(
                'migration', '0023_source_inventory_context_seed',
                'inventory_file', 'canonical_data_and_analytics_plan',
                'inventory_slug', 'fcc-area-census-block-api',
                'official_docs_checked_at', '2026-07-15'
            )
        ),
        (
            'gsa-site-scanning-api',
            NULL,
            'candidate',
            'Seeded from the roadmap-listed GSA official-domain context source for maintainer review.',
            jsonb_build_object(
                'migration', '0023_source_inventory_context_seed',
                'inventory_file', 'canonical_data_and_analytics_plan',
                'inventory_slug', 'gsa-site-scanning-api',
                'official_docs_checked_at', '2026-07-15'
            )
        )
)
INSERT INTO public.source_catalog_review_events (
    source_slug,
    previous_status,
    new_status,
    reviewer,
    reason,
    evidence
)
SELECT
    review_seed.source_slug,
    review_seed.previous_status,
    review_seed.new_status,
    'source-inventory-2026-07',
    review_seed.reason,
    review_seed.evidence
FROM review_seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.source_catalog_review_events AS existing
    WHERE existing.source_slug = review_seed.source_slug
      AND existing.endpoint_slug IS NULL
      AND existing.new_status = review_seed.new_status
      AND existing.reason = review_seed.reason
);

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0023_source_inventory_context_seed',
    23,
    'Private FCC and GSA jurisdiction/domain context catalog candidates.',
    jsonb_build_object(
        'source_catalog_candidates', ARRAY['fcc-area-api', 'gsa-site-scanning-api']::text[],
        'extractors_added', false,
        'public_facts_added', false
    )
)
ON CONFLICT (migration_key) DO UPDATE SET
    description = EXCLUDED.description,
    metadata = public.schema_migrations.metadata || EXCLUDED.metadata;

NOTIFY pgrst, 'reload schema';

COMMIT;
