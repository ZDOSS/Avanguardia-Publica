-- 0019_source_inventory_influence_spending_seed.sql
--
-- Seed the second reviewed P0 batch from the July 2026 government API inventory into
-- the private source catalog. These influence, rulemaking, spending, and procurement
-- rows are review candidates only; they do not add extractors, public facts, or
-- scraper dependencies.

SET statement_timeout = '30s';

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
        'lda-gov-api',
        'LDA.gov Lobbying Disclosure API',
        'United States Senate',
        'Secretary of the Senate / Clerk of the House',
        'legislative',
        'lobbying_influence',
        'api',
        'open',
        'unknown',
        NULL,
        'https://lda.senate.gov/api/v1/',
        'https://lda.senate.gov/system/public/',
        ARRAY['json']::text[],
        'Lobbying registrations LD-1, quarterly reports LD-2, and contributions reports LD-203.',
        'filing-driven',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'High-value influence graph source. Legacy site says it will no longer be available after 2026-07-31; verify LDA.gov transition before extractor work.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Moving',
            'repo_usage_status', 'Not wired; high-value official candidate',
            'repo_evidence', 'No current lobbying extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for LD-1/LD-2/LD-203 lobbying filings and influence graph.',
            'source_url', 'https://lda.senate.gov/system/public/'
        )
    ),
    (
        'federal-register-api',
        'Federal Register API',
        'National Archives and Records Administration / GPO / OFR',
        'Office of the Federal Register',
        'executive',
        'rulemaking_executive_actions',
        'api',
        'open',
        'none',
        NULL,
        'https://www.federalregister.gov/api/v1/',
        'https://www.federalregister.gov/reader-aids/developer-resources/rest-api',
        ARRAY['json', 'csv']::text[],
        'Federal Register documents, agencies, public inspection, and presidential documents.',
        'business daily',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Official source for regulatory actions, agency documents, presidential documents, and citations.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; high-value official candidate',
            'repo_evidence', 'No current Federal Register extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for agency actions, executive documents, rulemaking context, and citations.',
            'source_url', 'https://www.federalregister.gov/reader-aids/developer-resources/rest-api'
        )
    ),
    (
        'regulations-gov-api',
        'Regulations.gov API',
        'Environmental Protection Agency / eRulemaking Program',
        'Regulations.gov',
        'executive',
        'rulemaking_comments',
        'api',
        'free_key',
        'api_key',
        'api.data.gov',
        'https://api.regulations.gov/v4/',
        'https://open.gsa.gov/api/',
        ARRAY['json']::text[],
        'Dockets, documents, and comments; public comment submission endpoints also exist.',
        'ongoing',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Official rulemaking source candidate; watch API rate limits and comment text volume.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; high-value official candidate',
            'repo_evidence', 'No current Regulations.gov extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for rulemaking dockets, comments, and agency regulatory actions.',
            'source_url', 'https://open.gsa.gov/api/'
        )
    ),
    (
        'usaspending-api',
        'USAspending API',
        'Department of the Treasury',
        'Fiscal Service / USAspending.gov',
        'executive',
        'spending_awards',
        'api',
        'open',
        'none',
        NULL,
        'https://api.usaspending.gov/api/v2/',
        'https://api.usaspending.gov/',
        ARRAY['json']::text[],
        'Federal awards, spending, recipients, agencies, accounts, and transactions.',
        'daily / recurring',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'High-value public money graph source; no auth required for most endpoints.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; high-value official candidate',
            'repo_evidence', 'No current USAspending extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for federal spending, awards, recipients, and politician/organization network enrichment.',
            'source_url', 'https://api.usaspending.gov/'
        )
    ),
    (
        'sam-entity-management-api',
        'SAM.gov Entity Management API',
        'General Services Administration',
        'SAM.gov',
        'executive',
        'entity_vendors',
        'api',
        'free_key',
        'api_key',
        'SAM.gov',
        'https://api.sam.gov/entity-information/v3/entities',
        'https://open.gsa.gov/api/',
        ARRAY['json']::text[],
        'Registered entity detail information.',
        'ongoing',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Organization/entity identity candidate; respect non-public fields and access rules.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; high-value official candidate',
            'repo_evidence', 'No current SAM.gov entity extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for organization/entity identity resolution and contractor graph enrichment.',
            'source_url', 'https://open.gsa.gov/api/'
        )
    ),
    (
        'sam-contract-awards-api',
        'SAM.gov Contract Awards API',
        'General Services Administration',
        'SAM.gov',
        'executive',
        'procurement_awards',
        'api',
        'free_key',
        'api_key',
        'SAM.gov',
        'https://api.sam.gov/prod/contract/v1/awards',
        'https://open.gsa.gov/api/',
        ARRAY['json']::text[],
        'Contract awards from SAM.gov using searchable parameters.',
        'ongoing',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Contract recipient and agency relationship graph candidate; cross-link with USAspending award IDs and FPDS history.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'New candidate / not currently wired',
            'repo_next_action', 'Evaluate for fit, auth, quota, schema, and official-source provenance before adding an extractor.',
            'source_url', 'https://open.gsa.gov/api/'
        )
    ),
    (
        'sam-opportunities-public-api',
        'SAM.gov Get Opportunities Public API',
        'General Services Administration',
        'SAM.gov',
        'executive',
        'procurement_opportunities',
        'api',
        'free_key',
        'api_key',
        'SAM.gov',
        'https://api.sam.gov/opportunities/v2/search',
        'https://open.gsa.gov/api/',
        ARRAY['json']::text[],
        'Published federal contract opportunity details with pagination.',
        'ongoing',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Public opportunity search candidate; opportunity management write APIs are restricted/authorized.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'New candidate / not currently wired',
            'repo_next_action', 'Evaluate for fit, auth, quota, schema, and official-source provenance before adding an extractor.',
            'source_url', 'https://open.gsa.gov/api/'
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
    notes = EXCLUDED.notes,
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
    ('lda-gov-api', 'api-v1-legacy', 'LDA.gov legacy public API v1', 'api', 'https://lda.senate.gov/api/v1/', 'https://lda.senate.gov/system/public/', ARRAY['json']::text[], 'open', 'unknown', NULL, 'filing-driven', 'candidate', 'Legacy public API location; verify LDA.gov transition before extractor work.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('federal-register-api', 'api-v1', 'Federal Register API v1', 'api', 'https://www.federalregister.gov/api/v1/', 'https://www.federalregister.gov/reader-aids/developer-resources/rest-api', ARRAY['json', 'csv']::text[], 'open', 'none', NULL, 'business daily', 'candidate', 'Official Federal Register API.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('regulations-gov-api', 'api-v4', 'Regulations.gov API v4', 'api', 'https://api.regulations.gov/v4/', 'https://open.gsa.gov/api/', ARRAY['json']::text[], 'free_key', 'api_key', 'api.data.gov', 'ongoing', 'candidate', 'Official rulemaking API; comment volume requires careful scope.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('usaspending-api', 'api-v2', 'USAspending API v2', 'api', 'https://api.usaspending.gov/api/v2/', 'https://api.usaspending.gov/', ARRAY['json']::text[], 'open', 'none', NULL, 'daily / recurring', 'candidate', 'Official spending and award API.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('sam-entity-management-api', 'entities-v3', 'SAM.gov Entity Management API v3', 'api', 'https://api.sam.gov/entity-information/v3/entities', 'https://open.gsa.gov/api/', ARRAY['json']::text[], 'free_key', 'api_key', 'SAM.gov', 'ongoing', 'candidate', 'Entity detail API; access rules need review before ingestion.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('sam-contract-awards-api', 'awards-v1', 'SAM.gov Contract Awards API v1', 'api', 'https://api.sam.gov/prod/contract/v1/awards', 'https://open.gsa.gov/api/', ARRAY['json']::text[], 'free_key', 'api_key', 'SAM.gov', 'ongoing', 'candidate', 'Contract awards API candidate.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status')),
    ('sam-opportunities-public-api', 'opportunities-v2-search', 'SAM.gov opportunities v2 search API', 'api', 'https://api.sam.gov/opportunities/v2/search', 'https://open.gsa.gov/api/', ARRAY['json']::text[], 'free_key', 'api_key', 'SAM.gov', 'ongoing', 'candidate', 'Public opportunities search API candidate.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status'))
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
    notes = EXCLUDED.notes,
    metadata = public.source_catalog_endpoints.metadata || EXCLUDED.metadata;

WITH review_seed(source_slug, reason, evidence) AS (
    VALUES
        ('lda-gov-api', 'Seeded from July 2026 source inventory for official lobbying-source review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('federal-register-api', 'Seeded from July 2026 source inventory for official rulemaking-source review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('regulations-gov-api', 'Seeded from July 2026 source inventory for official rulemaking-comment review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('usaspending-api', 'Seeded from July 2026 source inventory for official spending-source review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('sam-entity-management-api', 'Seeded from July 2026 source inventory for official entity-source review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('sam-contract-awards-api', 'Seeded from July 2026 source inventory for official procurement-awards review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status')),
        ('sam-opportunities-public-api', 'Seeded from July 2026 source inventory for official procurement-opportunities review.', jsonb_build_object('migration', '0019_source_inventory_influence_spending_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status'))
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
    NULL,
    'candidate',
    'source-inventory-2026-07',
    review_seed.reason,
    review_seed.evidence
FROM review_seed
WHERE NOT EXISTS (
    SELECT 1
    FROM public.source_catalog_review_events AS existing
    WHERE existing.source_slug = review_seed.source_slug
      AND existing.endpoint_slug IS NULL
      AND existing.new_status = 'candidate'
      AND existing.reason = review_seed.reason
);

NOTIFY pgrst, 'reload schema';
