-- 0018_source_catalog_reports.sql
--
-- Private source-catalog reporting views for the Phase 4/6 review workflow.
-- These reports summarize catalog health and candidate next actions without adding
-- public reads, extractors, loader writes, or scraper dependencies.

SET statement_timeout = '30s';

CREATE OR REPLACE VIEW public.source_catalog_report_health_overview AS
SELECT
    count(*) AS total_sources,
    count(*) FILTER (WHERE status = 'approved') AS approved_sources,
    count(*) FILTER (WHERE status = 'candidate') AS candidate_sources,
    count(*) FILTER (WHERE status = 'deferred') AS deferred_sources,
    count(*) FILTER (WHERE status = 'blocked') AS blocked_sources,
    count(*) FILTER (WHERE repo_fit = 'wired') AS wired_sources,
    count(*) FILTER (WHERE repo_fit = 'needs_review') AS needs_review_sources,
    count(*) FILTER (WHERE metadata ? 'inventory_file') AS inventory_seeded_sources,
    (
        SELECT count(*)
        FROM public.source_catalog_endpoints
    ) AS total_endpoints,
    (
        SELECT count(*)
        FROM public.source_catalog_endpoints
        WHERE status = 'candidate'
    ) AS candidate_endpoints,
    (
        SELECT count(*)
        FROM public.source_catalog_validation_pending_review
    ) AS pending_review_sources,
    (
        SELECT count(*)
        FROM public.source_catalog_validation_duplicate_endpoint_urls
    ) AS duplicate_endpoint_url_groups,
    (
        SELECT count(*)
        FROM public.source_catalog_validation_unlinked_source_systems
    ) AS unlinked_source_systems
FROM public.source_catalog_sources;

CREATE OR REPLACE VIEW public.source_catalog_report_status_rollup AS
SELECT
    priority,
    category,
    status,
    repo_fit,
    verified_lane,
    access_level,
    auth_type,
    count(*) AS source_count,
    count(*) FILTER (WHERE metadata ? 'inventory_file') AS inventory_seeded_sources,
    count(*) FILTER (WHERE repo_fit = 'wired') AS wired_sources,
    count(*) FILTER (WHERE status IN ('candidate', 'deferred', 'blocked')) AS review_queue_sources
FROM public.source_catalog_sources
GROUP BY
    priority,
    category,
    status,
    repo_fit,
    verified_lane,
    access_level,
    auth_type;

CREATE OR REPLACE VIEW public.source_catalog_report_candidate_queue AS
WITH endpoint_counts AS (
    SELECT
        source_slug,
        count(*) AS endpoint_count,
        count(*) FILTER (WHERE status = 'candidate') AS candidate_endpoint_count,
        count(*) FILTER (WHERE status = 'approved') AS approved_endpoint_count,
        count(*) FILTER (WHERE access_level IN ('free_key', 'free_tier')) AS keyed_or_tiered_endpoint_count
    FROM public.source_catalog_endpoints
    GROUP BY source_slug
),
latest_source_review AS (
    SELECT DISTINCT ON (source_slug)
        source_slug,
        new_status AS latest_review_status,
        reviewer AS latest_reviewer,
        reviewed_at AS latest_reviewed_at,
        reason AS latest_review_reason
    FROM public.source_catalog_review_events
    WHERE endpoint_slug IS NULL
    ORDER BY source_slug, reviewed_at DESC, id DESC
)
SELECT
    s.slug,
    s.name,
    s.priority,
    s.category,
    s.status,
    s.repo_fit,
    s.verified_lane,
    s.access_level,
    s.auth_type,
    s.credential_provider,
    COALESCE(ec.endpoint_count, 0) AS endpoint_count,
    COALESCE(ec.candidate_endpoint_count, 0) AS candidate_endpoint_count,
    COALESCE(ec.approved_endpoint_count, 0) AS approved_endpoint_count,
    COALESCE(ec.keyed_or_tiered_endpoint_count, 0) AS keyed_or_tiered_endpoint_count,
    s.metadata ->> 'repo_usage_status' AS repo_usage_status,
    s.metadata ->> 'repo_next_action' AS repo_next_action,
    s.notes,
    lr.latest_review_status,
    lr.latest_reviewer,
    lr.latest_reviewed_at,
    lr.latest_review_reason,
    CASE s.priority
        WHEN 'P0' THEN 0
        WHEN 'P1' THEN 1
        WHEN 'P2' THEN 2
        WHEN 'P3' THEN 3
        ELSE 9
    END AS priority_rank
FROM public.source_catalog_sources AS s
LEFT JOIN endpoint_counts AS ec ON ec.source_slug = s.slug
LEFT JOIN latest_source_review AS lr ON lr.source_slug = s.slug
WHERE s.status IN ('candidate', 'deferred', 'blocked')
   OR s.repo_fit IN ('candidate', 'needs_review', 'deferred', 'blocked');

CREATE OR REPLACE VIEW public.source_catalog_report_endpoint_rollup AS
SELECT
    s.priority,
    s.category,
    e.status,
    e.endpoint_type,
    e.access_level,
    e.auth_type,
    count(*) AS endpoint_count,
    count(DISTINCT e.source_slug) AS source_count,
    count(*) FILTER (WHERE e.metadata ? 'inventory_file') AS inventory_seeded_endpoints
FROM public.source_catalog_endpoints AS e
JOIN public.source_catalog_sources AS s ON s.slug = e.source_slug
GROUP BY
    s.priority,
    s.category,
    e.status,
    e.endpoint_type,
    e.access_level,
    e.auth_type;

CREATE OR REPLACE VIEW public.source_catalog_report_latest_reviews AS
SELECT DISTINCT ON (e.source_slug, e.endpoint_slug)
    e.source_slug,
    s.name AS source_name,
    e.endpoint_slug,
    ep.display_name AS endpoint_name,
    e.previous_status,
    e.new_status,
    e.reviewer,
    e.reviewed_at,
    e.reason,
    e.evidence
FROM public.source_catalog_review_events AS e
JOIN public.source_catalog_sources AS s ON s.slug = e.source_slug
LEFT JOIN public.source_catalog_endpoints AS ep
  ON ep.source_slug = e.source_slug
 AND ep.endpoint_slug = e.endpoint_slug
ORDER BY e.source_slug, e.endpoint_slug, e.reviewed_at DESC, e.id DESC;

REVOKE ALL ON TABLE public.source_catalog_report_health_overview FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_report_status_rollup FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_report_candidate_queue FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_report_endpoint_rollup FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_catalog_report_latest_reviews FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE public.source_catalog_report_health_overview TO service_role;
GRANT SELECT ON TABLE public.source_catalog_report_status_rollup TO service_role;
GRANT SELECT ON TABLE public.source_catalog_report_candidate_queue TO service_role;
GRANT SELECT ON TABLE public.source_catalog_report_endpoint_rollup TO service_role;
GRANT SELECT ON TABLE public.source_catalog_report_latest_reviews TO service_role;

NOTIFY pgrst, 'reload schema';
