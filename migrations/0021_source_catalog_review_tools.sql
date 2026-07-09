-- 0021_source_catalog_review_tools.sql
--
-- Private maintainer tooling for source-catalog review. This adds an actionable
-- worklist report and service-role-only RPCs that update review status while
-- writing audit events. It does not add public reads, scraper dependencies, or
-- public profile facts.

SET statement_timeout = '30s';

CREATE OR REPLACE VIEW public.source_catalog_report_review_worklist AS
WITH endpoint_summary AS (
    SELECT
        source_slug,
        count(*) AS endpoint_count,
        count(*) FILTER (WHERE status = 'candidate') AS candidate_endpoint_count,
        count(*) FILTER (WHERE status = 'approved') AS approved_endpoint_count,
        count(*) FILTER (
            WHERE access_level IN ('free_key', 'free_tier')
               OR auth_type IN ('api_key', 'oauth')
        ) AS credential_review_endpoint_count
    FROM public.source_catalog_endpoints
    GROUP BY source_slug
),
latest_source_review AS (
    SELECT DISTINCT ON (source_slug)
        source_slug,
        previous_status AS latest_previous_status,
        new_status AS latest_review_status,
        reviewer AS latest_reviewer,
        reviewed_at AS latest_reviewed_at,
        reason AS latest_review_reason,
        evidence AS latest_review_evidence
    FROM public.source_catalog_review_events
    WHERE endpoint_slug IS NULL
    ORDER BY source_slug, reviewed_at DESC, id DESC
)
SELECT
    s.slug,
    s.name,
    s.agency,
    s.sub_agency,
    s.branch,
    s.category,
    s.source_type,
    s.priority,
    s.status,
    s.repo_fit,
    s.verified_lane,
    s.access_level,
    s.auth_type,
    s.credential_provider,
    s.base_url,
    s.docs_url,
    COALESCE(s.metadata ->> 'source_url', s.docs_url, s.base_url) AS source_url,
    s.metadata ->> 'inventory_slug' AS inventory_slug,
    s.metadata ->> 'repo_usage_status' AS repo_usage_status,
    s.metadata ->> 'repo_evidence' AS repo_evidence,
    s.metadata ->> 'repo_next_action' AS repo_next_action,
    s.notes,
    COALESCE(es.endpoint_count, 0) AS endpoint_count,
    COALESCE(es.candidate_endpoint_count, 0) AS candidate_endpoint_count,
    COALESCE(es.approved_endpoint_count, 0) AS approved_endpoint_count,
    COALESCE(es.credential_review_endpoint_count, 0) AS credential_review_endpoint_count,
    lr.latest_previous_status,
    lr.latest_review_status,
    lr.latest_reviewer,
    lr.latest_reviewed_at,
    lr.latest_review_reason,
    lr.latest_review_evidence,
    CASE
        WHEN lr.latest_reviewed_at IS NULL THEN NULL
        ELSE floor(EXTRACT(epoch FROM (now() - lr.latest_reviewed_at)) / 86400)::integer
    END AS latest_review_age_days,
    CASE
        WHEN s.status = 'blocked' OR s.repo_fit = 'blocked' THEN 'resolve_blocker'
        WHEN s.status = 'duplicate' OR s.repo_fit = 'duplicate' THEN 'verify_duplicate_mapping'
        WHEN s.status = 'deferred' OR s.repo_fit = 'deferred' THEN 'revisit_deferred_source'
        WHEN COALESCE(es.credential_review_endpoint_count, 0) > 0
             OR s.access_level IN ('free_key', 'free_tier')
             OR s.auth_type IN ('api_key', 'oauth') THEN 'credential_and_quota_review'
        WHEN s.verified_lane = 'verified' THEN 'official_source_review'
        WHEN s.verified_lane IN ('mixed', 'unverified') THEN 'trust_and_labeling_review'
        ELSE 'general_source_review'
    END AS review_focus,
    CASE s.priority
        WHEN 'P0' THEN 0
        WHEN 'P1' THEN 1
        WHEN 'P2' THEN 2
        WHEN 'P3' THEN 3
        ELSE 9
    END AS priority_rank
FROM public.source_catalog_sources AS s
LEFT JOIN endpoint_summary AS es ON es.source_slug = s.slug
LEFT JOIN latest_source_review AS lr ON lr.source_slug = s.slug
WHERE s.status IN ('candidate', 'deferred', 'duplicate', 'blocked')
   OR s.repo_fit IN ('candidate', 'needs_review', 'deferred', 'duplicate', 'blocked');

CREATE OR REPLACE FUNCTION public.review_source_catalog_source(
    p_source_slug text,
    p_new_status text,
    p_repo_fit text,
    p_reviewer text DEFAULT 'maintainer',
    p_reason text DEFAULT NULL,
    p_evidence jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    source_slug text,
    previous_status text,
    new_status text,
    previous_repo_fit text,
    new_repo_fit text,
    review_event_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_previous_status text;
    v_previous_repo_fit text;
    v_reviewer text;
    v_evidence jsonb;
    v_review_event_id uuid;
BEGIN
    IF NULLIF(btrim(COALESCE(p_source_slug, '')), '') IS NULL THEN
        RAISE EXCEPTION 'source slug is required' USING ERRCODE = '22023';
    END IF;

    IF p_new_status NOT IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked') THEN
        RAISE EXCEPTION 'invalid source status: %', p_new_status USING ERRCODE = '22023';
    END IF;

    IF p_repo_fit NOT IN ('wired', 'candidate', 'deferred', 'blocked', 'duplicate', 'retired', 'needs_review') THEN
        RAISE EXCEPTION 'invalid source repo_fit: %', p_repo_fit USING ERRCODE = '22023';
    END IF;

    IF NULLIF(btrim(COALESCE(p_reason, '')), '') IS NULL THEN
        RAISE EXCEPTION 'review reason is required' USING ERRCODE = '22023';
    END IF;

    SELECT s.status, s.repo_fit
    INTO v_previous_status, v_previous_repo_fit
    FROM public.source_catalog_sources AS s
    WHERE s.slug = p_source_slug
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source catalog source does not exist: %', p_source_slug USING ERRCODE = '23503';
    END IF;

    v_reviewer := COALESCE(NULLIF(btrim(p_reviewer), ''), 'maintainer');
    v_evidence := CASE
        WHEN p_evidence IS NULL THEN '{}'::jsonb
        WHEN jsonb_typeof(p_evidence) = 'object' THEN p_evidence
        ELSE jsonb_build_object('payload', p_evidence)
    END;

    UPDATE public.source_catalog_sources AS s
    SET
        status = p_new_status,
        repo_fit = p_repo_fit
    WHERE s.slug = p_source_slug;

    INSERT INTO public.source_catalog_review_events (
        source_slug,
        previous_status,
        new_status,
        reviewer,
        reason,
        evidence
    )
    VALUES (
        p_source_slug,
        v_previous_status,
        p_new_status,
        v_reviewer,
        p_reason,
        v_evidence || jsonb_build_object(
            'tool', 'review_source_catalog_source',
            'previous_repo_fit', v_previous_repo_fit,
            'new_repo_fit', p_repo_fit
        )
    )
    RETURNING id INTO v_review_event_id;

    RETURN QUERY
    SELECT
        p_source_slug,
        v_previous_status,
        p_new_status,
        v_previous_repo_fit,
        p_repo_fit,
        v_review_event_id;
END;
$$;

CREATE OR REPLACE FUNCTION public.review_source_catalog_endpoint(
    p_source_slug text,
    p_endpoint_slug text,
    p_new_status text,
    p_reviewer text DEFAULT 'maintainer',
    p_reason text DEFAULT NULL,
    p_evidence jsonb DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    source_slug text,
    endpoint_slug text,
    previous_status text,
    new_status text,
    review_event_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_previous_status text;
    v_reviewer text;
    v_evidence jsonb;
    v_review_event_id uuid;
BEGIN
    IF NULLIF(btrim(COALESCE(p_source_slug, '')), '') IS NULL THEN
        RAISE EXCEPTION 'source slug is required' USING ERRCODE = '22023';
    END IF;

    IF NULLIF(btrim(COALESCE(p_endpoint_slug, '')), '') IS NULL THEN
        RAISE EXCEPTION 'endpoint slug is required' USING ERRCODE = '22023';
    END IF;

    IF p_new_status NOT IN ('candidate', 'approved', 'deferred', 'duplicate', 'retired', 'blocked') THEN
        RAISE EXCEPTION 'invalid endpoint status: %', p_new_status USING ERRCODE = '22023';
    END IF;

    IF NULLIF(btrim(COALESCE(p_reason, '')), '') IS NULL THEN
        RAISE EXCEPTION 'review reason is required' USING ERRCODE = '22023';
    END IF;

    SELECT e.status
    INTO v_previous_status
    FROM public.source_catalog_endpoints AS e
    WHERE e.source_slug = p_source_slug
      AND e.endpoint_slug = p_endpoint_slug
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source catalog endpoint does not exist: %.%', p_source_slug, p_endpoint_slug USING ERRCODE = '23503';
    END IF;

    v_reviewer := COALESCE(NULLIF(btrim(p_reviewer), ''), 'maintainer');
    v_evidence := CASE
        WHEN p_evidence IS NULL THEN '{}'::jsonb
        WHEN jsonb_typeof(p_evidence) = 'object' THEN p_evidence
        ELSE jsonb_build_object('payload', p_evidence)
    END;

    UPDATE public.source_catalog_endpoints AS e
    SET status = p_new_status
    WHERE e.source_slug = p_source_slug
      AND e.endpoint_slug = p_endpoint_slug;

    INSERT INTO public.source_catalog_review_events (
        source_slug,
        endpoint_slug,
        previous_status,
        new_status,
        reviewer,
        reason,
        evidence
    )
    VALUES (
        p_source_slug,
        p_endpoint_slug,
        v_previous_status,
        p_new_status,
        v_reviewer,
        p_reason,
        v_evidence || jsonb_build_object(
            'tool', 'review_source_catalog_endpoint'
        )
    )
    RETURNING id INTO v_review_event_id;

    RETURN QUERY
    SELECT
        p_source_slug,
        p_endpoint_slug,
        v_previous_status,
        p_new_status,
        v_review_event_id;
END;
$$;

REVOKE ALL ON TABLE public.source_catalog_report_review_worklist FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.source_catalog_report_review_worklist TO service_role;

REVOKE ALL ON FUNCTION public.review_source_catalog_source(text, text, text, text, text, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.review_source_catalog_endpoint(text, text, text, text, text, jsonb) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.review_source_catalog_source(text, text, text, text, text, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.review_source_catalog_endpoint(text, text, text, text, text, jsonb) TO service_role;

NOTIFY pgrst, 'reload schema';
