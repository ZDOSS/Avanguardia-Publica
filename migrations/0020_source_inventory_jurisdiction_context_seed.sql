-- 0020_source_inventory_jurisdiction_context_seed.sql
--
-- Seed the P0 jurisdiction/context Census batch and reconcile inventory rows that
-- duplicate already-wired catalog sources. These rows are private catalog/review
-- metadata only; they do not add extractors, public facts, or scraper dependencies.

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
        'census-data-api',
        'Census Data API',
        'Department of Commerce',
        'U.S. Census Bureau',
        'executive',
        'jurisdiction_demographics',
        'api',
        'free_key',
        'api_key',
        'Census Bureau',
        'https://api.census.gov/data/',
        'https://www.census.gov/data/developers/data-sets.html',
        ARRAY['json']::text[],
        'Census Bureau datasets including ACS, decennial census, population estimates, and economic programs.',
        'dataset-specific',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Jurisdiction and demographic context candidate; use dataset metadata endpoints and store dataset vintage.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_slug', 'census-data-api',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; useful normalization/context candidate',
            'repo_evidence', 'No current Census extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Add for district, place, ACS, demographic, and geographic normalization context.',
            'source_url', 'https://www.census.gov/data/developers/data-sets.html'
        )
    ),
    (
        'census-geocoder-api',
        'Census Geocoder API',
        'Department of Commerce',
        'U.S. Census Bureau',
        'executive',
        'jurisdiction_geocoding',
        'api',
        'open',
        'none',
        NULL,
        'https://geocoding.geo.census.gov/geocoder/',
        'https://geocoding.geo.census.gov/geocoder/',
        ARRAY['json', 'xml']::text[],
        'Address geocoding to Census geography and entities.',
        'dataset benchmark-specific',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Address/geography normalization candidate; store benchmark, vintage, confidence, and match type.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_slug', 'census-geocoder-api',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Not wired; useful normalization/context candidate',
            'repo_evidence', 'No current Census geocoder extractor found in scraper/main.py or scraper/extractors.',
            'repo_next_action', 'Use for address/geography normalization when records include locations.',
            'source_url', 'https://geocoding.geo.census.gov/geocoder/'
        )
    ),
    (
        'census-tigerweb-geoservices',
        'Census TIGERweb GeoServices',
        'Department of Commerce',
        'U.S. Census Bureau',
        'executive',
        'jurisdiction_boundaries',
        'api',
        'open',
        'none',
        NULL,
        'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/',
        'https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html',
        ARRAY['geojson', 'json', 'arcgis_rest']::text[],
        'Census geographies, congressional districts, states, counties, tracts, blocks, and other boundaries.',
        'vintage-specific',
        'P0',
        'candidate',
        'verified',
        'needs_review',
        DATE '2026-07-03',
        'Authoritative boundary context candidate; store vintage/year with every geometry relationship.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_slug', 'census-tigerweb-geoservices',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'New candidate / not currently wired',
            'repo_next_action', 'Evaluate for fit, auth, quota, schema, and official-source provenance before adding an extractor.',
            'source_url', 'https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html'
        )
    ),
    (
        'openfec',
        'OpenFEC API',
        'Federal Election Commission',
        'OpenFEC',
        'campaign_finance',
        'campaign_finance',
        'api',
        'free_key',
        'api_key',
        'api.data.gov',
        'https://api.open.fec.gov/v1/',
        'https://api.open.fec.gov/developers/',
        ARRAY['json']::text[],
        'Candidates, committees, filings, receipts, disbursements, schedules, elections, and campaign finance summaries.',
        'ongoing / filing-driven',
        'P0',
        'approved',
        'verified',
        'wired',
        DATE '2026-07-03',
        'Existing campaign-donor extractor source; inventory duplicate slug fec-openfec-api is reconciled here.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_slug', 'fec-openfec-api',
            'inventory_status', 'Verified public docs',
            'repo_usage_status', 'Already used in repo',
            'repo_evidence', 'scraper/extractors/fec.py uses https://api.open.fec.gov/v1 with FEC_API_KEY/api_key and writes campaign_donors.',
            'repo_next_action', 'Mark as existing extractor. Future work: broaden beyond recent receipts if quotas/storage allow.',
            'source_url', 'https://api.open.fec.gov/developers/'
        )
    ),
    (
        'house-clerk',
        'U.S. House Clerk financial disclosures',
        'U.S. House of Representatives',
        'Office of the Clerk',
        'legislative',
        'financial_disclosures',
        'bulk_data',
        'open',
        'none',
        NULL,
        'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/',
        'https://disclosures-clerk.house.gov/',
        ARRAY['xml', 'pdf']::text[],
        'House member/candidate annual reports and periodic transaction report filing index and official PDFs.',
        'filing-driven',
        'P0',
        'approved',
        'verified',
        'wired',
        DATE '2026-07-03',
        'Existing House financial-disclosure index source; inventory duplicate slug house-clerk-financial-disclosures is reconciled here.',
        jsonb_build_object(
            'inventory_file', 'us_government_api_seed_inventory_repo_status',
            'inventory_slug', 'house-clerk-financial-disclosures',
            'inventory_status', 'Verified in repo / official',
            'repo_usage_status', 'Already used in repo',
            'repo_evidence', 'scraper/extractors/financial_disclosures.py downloads House Clerk annual financial disclosure ZIP/XML indexes; scraper/main.py builds the index for current + prior year.',
            'repo_next_action', 'Mark as existing extractor. Future work: add PDF transaction parsing or Senate/state disclosure sources separately.',
            'source_url', 'https://disclosures-clerk.house.gov/'
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
    ('census-data-api', 'data-api', 'Census Data API', 'api', 'https://api.census.gov/data/', 'https://www.census.gov/data/developers/data-sets.html', ARRAY['json']::text[], 'free_key', 'api_key', 'Census Bureau', 'dataset-specific', 'candidate', 'Dataset-specific Census API endpoint family; store dataset and vintage with any future facts.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-data-api')),
    ('census-geocoder-api', 'geocoder', 'Census Geocoder API', 'api', 'https://geocoding.geo.census.gov/geocoder/', 'https://geocoding.geo.census.gov/geocoder/', ARRAY['json', 'xml']::text[], 'open', 'none', NULL, 'dataset benchmark-specific', 'candidate', 'Address geocoder endpoint family; benchmark and vintage must be explicit.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-geocoder-api')),
    ('census-tigerweb-geoservices', 'tigerweb-rest-services', 'Census TIGERweb REST services', 'api', 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/', 'https://tigerweb.geo.census.gov/tigerwebmain/TIGERweb_restmapservice.html', ARRAY['geojson', 'json', 'arcgis_rest']::text[], 'open', 'none', NULL, 'vintage-specific', 'candidate', 'Boundary service endpoint family; geometry relationships need vintage/year provenance.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-tigerweb-geoservices')),
    ('openfec', 'api-v1', 'OpenFEC API v1', 'api', 'https://api.open.fec.gov/v1/', 'https://api.open.fec.gov/developers/', ARRAY['json']::text[], 'free_key', 'api_key', 'api.data.gov', 'ongoing / filing-driven', 'approved', 'Existing campaign-donor endpoint; inventory duplicate slug fec-openfec-api is reconciled here.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'fec-openfec-api')),
    ('house-clerk', 'financial-disclosure-bulk', 'House Clerk financial disclosure bulk index', 'bulk_file', 'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/', 'https://disclosures-clerk.house.gov/', ARRAY['xml', 'pdf']::text[], 'open', 'none', NULL, 'filing-driven', 'approved', 'Existing House filing-index endpoint; inventory duplicate slug house-clerk-financial-disclosures is reconciled here.', jsonb_build_object('inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'house-clerk-financial-disclosures'))
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
        ('census-data-api', NULL, 'candidate', 'Seeded from July 2026 source inventory for Census demographic/context review.', jsonb_build_object('migration', '0020_source_inventory_jurisdiction_context_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-data-api')),
        ('census-geocoder-api', NULL, 'candidate', 'Seeded from July 2026 source inventory for Census geocoding/context review.', jsonb_build_object('migration', '0020_source_inventory_jurisdiction_context_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-geocoder-api')),
        ('census-tigerweb-geoservices', NULL, 'candidate', 'Seeded from July 2026 source inventory for Census boundary/context review.', jsonb_build_object('migration', '0020_source_inventory_jurisdiction_context_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'census-tigerweb-geoservices')),
        ('openfec', NULL, 'approved', 'Reconciled July 2026 inventory slug fec-openfec-api to existing wired OpenFEC catalog source.', jsonb_build_object('migration', '0020_source_inventory_jurisdiction_context_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'fec-openfec-api', 'reconciled_to_source_slug', 'openfec')),
        ('house-clerk', NULL, 'approved', 'Reconciled July 2026 inventory slug house-clerk-financial-disclosures to existing wired House Clerk catalog source.', jsonb_build_object('migration', '0020_source_inventory_jurisdiction_context_seed', 'inventory_file', 'us_government_api_seed_inventory_repo_status', 'inventory_slug', 'house-clerk-financial-disclosures', 'reconciled_to_source_slug', 'house-clerk'))
),
review_rows AS (
    SELECT
        review_seed.source_slug,
        CASE
            WHEN review_seed.source_slug IN ('openfec', 'house-clerk') THEN current_source.status
            ELSE review_seed.previous_status
        END AS previous_status,
        review_seed.new_status,
        review_seed.reason,
        review_seed.evidence
    FROM review_seed
    LEFT JOIN public.source_catalog_sources AS current_source
      ON current_source.slug = review_seed.source_slug
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
    review_rows.source_slug,
    review_rows.previous_status,
    review_rows.new_status,
    'source-inventory-2026-07',
    review_rows.reason,
    review_rows.evidence
FROM review_rows
WHERE NOT EXISTS (
    SELECT 1
    FROM public.source_catalog_review_events AS existing
    WHERE existing.source_slug = review_rows.source_slug
      AND existing.endpoint_slug IS NULL
      AND existing.new_status = review_rows.new_status
      AND existing.reason = review_rows.reason
);

NOTIFY pgrst, 'reload schema';
