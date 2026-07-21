-- 0025_house_roll_call_source_review.sql
--
-- Phase 4 review decision for the official House Clerk roll-call XML feed.
--
-- This migration approves the already-wired shadow extractor and records the
-- provenance, retention, attribution, health, and disable contract for a future
-- authoritative ingestion path. It does not create vote tables, write public
-- vote facts, or enable an authoritative production write path.
--
-- Because current scraper behavior does not depend on this private review-only
-- decision, schema preflight remains on 0024. The separate ingestion migration
-- must advance the required preflight marker before enabling any House writes.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_endpoint_status text;
    v_evidence jsonb := jsonb_build_object(
        'migration', '0025_house_roll_call_source_review',
        'reviewed_at', '2026-07-21',
        'source_url', 'https://clerk.house.gov/Votes',
        'rights_url', 'https://clerk.house.gov/PrivacyPolicy',
        'shadow_run_ids', jsonb_build_array(
            '29673051187',
            '29716133242',
            '29717007354',
            '29800415718',
            '29868730671'
        ),
        'shadow_runs_observed', 5,
        'shadow_roll_calls_per_run', 25,
        'shadow_member_vote_observations', 53996,
        'shadow_exact_bioguide_matches', 53996,
        'shadow_unmatched_bioguide_ids', 0,
        'shadow_govtrack_vote_cast_matches', 53971,
        'shadow_govtrack_vote_not_observed', 25,
        'shadow_govtrack_vote_cast_mismatches', 0,
        'join_policy', 'exact_xml_name_id_to_bioguide_only',
        'verified_lane', 'verified',
        'ingestion_method', 'house_clerk_roll_call_xml',
        'roll_call_source_record_key', 'house:{congress}:{session}:{roll_call_number}',
        'member_vote_source_record_key', 'house:{congress}:{session}:{roll_call_number}:{bioguide_id}',
        'rights', jsonb_build_object(
            'classification', 'official_public_information',
            'decision', 'Retain and republish normalized facts with Office of the Clerk citation.',
            'checked_at', '2026-07-21'
        ),
        'retention', jsonb_build_object(
            'normalized_roll_calls', 'retain',
            'normalized_member_votes', 'retain',
            'source_record_id', 'retain',
            'fetched_url', 'retain',
            'fetched_at', 'retain',
            'payload_hash', 'retain',
            'raw_xml', 'not_retained'
        ),
        'attribution', jsonb_build_object(
            'label', 'Office of the Clerk, U.S. House of Representatives',
            'link_required', true,
            'source_url_required', true
        ),
        'health_policy', jsonb_build_object(
            'report_attempts_successes_failures_and_skips', true,
            'degraded_behavior', 'fail_closed_for_new_house_writes_and_retain_last_valid_rows'
        ),
        'disable_path', 'disable_authoritative_house_writes_and_return_to_shadow_only_without_deleting_provenance_or_identity_mappings',
        'production_write_status', 'disabled_pending_separate_ingestion_review'
    );
BEGIN
    -- A recorded marker means this forward-only review has already run. Never
    -- replay it and overwrite a later source retirement or other review choice.
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0025_house_roll_call_source_review'
    ) THEN
        RETURN;
    END IF;

    SELECT status, repo_fit
    INTO v_source_status, v_source_repo_fit
    FROM public.source_catalog_sources
    WHERE slug = 'house-clerk-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog row is missing: house-clerk-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT status
    INTO v_endpoint_status
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog endpoint is missing: house-clerk-roll-call-xml.evs-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    PERFORM 1
    FROM public.source_systems
    WHERE key = 'house-clerk'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source system is missing: house-clerk'
            USING ERRCODE = '23503';
    END IF;

    -- Do not silently overwrite an out-of-band maintainer decision. If the live
    -- catalog changed after shadow review, stop for a fresh review instead.
    IF v_source_status IS DISTINCT FROM 'candidate'
       OR v_source_repo_fit IS DISTINCT FROM 'needs_review'
       OR v_endpoint_status IS DISTINCT FROM 'candidate' THEN
        RAISE EXCEPTION
            'House roll-call source review expected candidate/needs_review/candidate, found %/%/%',
            v_source_status,
            v_source_repo_fit,
            v_endpoint_status
            USING ERRCODE = '55000';
    END IF;

    PERFORM public.review_source_catalog_source(
        p_source_slug => 'house-clerk-roll-call-xml',
        p_new_status => 'approved',
        p_repo_fit => 'wired',
        p_reviewer => 'phase-4-house-source-review',
        p_reason => 'Approved after five successful bounded shadow reconciliations with exact Bioguide coverage and zero vote-cast conflicts; approval does not enable production writes.',
        p_evidence => v_evidence || jsonb_build_object('review_scope', 'source')
    );

    PERFORM public.review_source_catalog_endpoint(
        p_source_slug => 'house-clerk-roll-call-xml',
        p_endpoint_slug => 'evs-roll-call-feed',
        p_new_status => 'approved',
        p_reviewer => 'phase-4-house-source-review',
        p_reason => 'Approved for the existing bounded shadow extractor; normalized production writes remain disabled pending a separate conflict-safe ingestion review.',
        p_evidence => v_evidence || jsonb_build_object('review_scope', 'endpoint')
    );

    UPDATE public.source_catalog_sources
    SET
        verified_at = DATE '2026-07-21',
        notes = 'Official House roll-call source approved after five bounded shadow runs. The extractor is wired for reconciliation only; authoritative/public vote writes remain disabled pending a separate reviewed ingestion path.',
        metadata = metadata || jsonb_build_object(
            'repo_usage_status', 'Wired as a bounded read-only reconciliation shadow; authoritative writes disabled.',
            'repo_evidence', 'Five successful runs produced 53,996 exact Bioguide joins, zero unmatched IDs, and zero vote-cast conflicts.',
            'repo_next_action', 'Add a conflict-safe provenance and ingestion path in a separate reviewed migration and PR.',
            'ingestion_status', 'shadow_only',
            'production_write_status', 'disabled_pending_separate_ingestion_review',
            'source_review', v_evidence
        )
    WHERE slug = 'house-clerk-roll-call-xml';

    UPDATE public.source_catalog_endpoints
    SET
        notes = 'Approved official endpoint used by the bounded shadow extractor. Production vote writes remain disabled.',
        metadata = metadata || jsonb_build_object(
            'ingestion_status', 'shadow_only',
            'join_policy', 'exact_xml_name_id_to_bioguide_only',
            'raw_xml_retained', false,
            'production_write_status', 'disabled_pending_separate_ingestion_review'
        )
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed';

    INSERT INTO public.source_catalog_source_system_links (
        source_slug,
        source_system_key,
        link_type,
        notes
    )
    VALUES (
        'house-clerk-roll-call-xml',
        'house-clerk',
        'same_source',
        'Official House Clerk roll-call catalog entry; distinct from the existing financial-disclosure catalog entry but owned by the same verified source system.'
    )
    ON CONFLICT (source_slug, source_system_key, link_type) DO UPDATE SET
        notes = EXCLUDED.notes;

    UPDATE public.source_systems
    SET notes = 'Official House Clerk source used for House financial-disclosure filings and roll-call records.'
    WHERE key = 'house-clerk';

    INSERT INTO public.schema_migrations (
        migration_key,
        migration_version,
        description,
        metadata
    )
    VALUES (
        '0025_house_roll_call_source_review',
        25,
        'Approve the official House Clerk roll-call source for shadow use and record its future-ingestion contract.',
        jsonb_build_object(
            'source_slug', 'house-clerk-roll-call-xml',
            'endpoint_slug', 'evs-roll-call-feed',
            'source_status', 'approved',
            'repo_fit', 'wired',
            'ingestion_status', 'shadow_only',
            'production_writes_enabled', false,
            'scraper_preflight_required', false,
            'shadow_run_ids', v_evidence -> 'shadow_run_ids'
        )
    );
END
$migration$;

COMMIT;
