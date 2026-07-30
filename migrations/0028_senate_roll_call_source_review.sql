-- 0028_senate_roll_call_source_review.sql
--
-- Phase 4 review decision for the official U.S. Senate roll-call XML feed.
--
-- This migration approves the already-wired, bounded reconciliation shadow and
-- records the provenance, retention, attribution, health, and disable contract
-- for a future authoritative ingestion path. It does not create vote tables,
-- write source records or public vote facts, or enable Senate production writes.
--
-- Because current scraper behavior does not depend on this private review-only
-- decision, schema preflight remains on 0027. A separate provenance/ingestion
-- migration must advance the required preflight marker before enabling writes.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_endpoint_status text;
    v_source_system_display_name text;
    v_source_system_kind text;
    v_source_system_trust_level text;
    v_source_system_verified boolean;
    v_evidence jsonb := jsonb_build_object(
        'migration', '0028_senate_roll_call_source_review',
        'reviewed_at', '2026-07-29',
        'source_url', 'https://www.senate.gov/legislative/LIS/roll_call_votes/',
        'rights_url', 'https://www.senate.gov/general/privacy.htm',
        'corrected_shadow_run_ids', jsonb_build_array(
            '30418108958',
            '30420913210'
        ),
        'corrected_shadow_runs_observed', 2,
        'corrected_shadow_roll_calls_per_run', 25,
        'corrected_shadow_roll_calls', 50,
        'corrected_shadow_member_vote_observations', 4996,
        'corrected_shadow_exact_lis_matches', 4996,
        'corrected_shadow_unmatched_lis_ids', 0,
        'corrected_shadow_missing_bioguide_crosswalks', 0,
        'corrected_shadow_govtrack_roll_calls_reconciled', 50,
        'corrected_shadow_govtrack_roll_calls_not_observed', 0,
        'corrected_shadow_govtrack_vote_cast_matches', 4996,
        'corrected_shadow_govtrack_vote_not_observed', 0,
        'corrected_shadow_govtrack_vote_cast_mismatches', 0,
        'corrected_shadow_source_requests', 154,
        'corrected_shadow_source_request_successes', 154,
        'corrected_shadow_source_request_failures', 0,
        'corrected_shadow_source_request_skips', 0,
        'comparison_implementation_merge_commit', 'e6e7524af7d5049e727faa5d930b8288df85891e',
        'legacy_comparison_run_ids', jsonb_build_array(
            '30398945569',
            '30327173703',
            '30237220453',
            '30187599543',
            '30143118597',
            '30141173654',
            '29978439083'
        ),
        'legacy_comparison_member_vote_observations', 17486,
        'legacy_comparison_exact_lis_matches', 17486,
        'legacy_comparison_govtrack_vote_cast_matches', 15074,
        'legacy_comparison_govtrack_vote_not_observed', 2412,
        'legacy_comparison_govtrack_vote_cast_mismatches', 0,
        'legacy_comparison_not_observed_interpretation',
            'The former active-profile comparator and publication timing caused absent comparison observations; the official LIS identity joins remained exact.',
        'join_policy', 'exact_xml_lis_member_id_via_trusted_lis_to_bioguide_crosswalk',
        'canonical_person_join', 'exact_trusted_bioguide_owner_after_lis_crosswalk',
        'verified_lane', 'verified',
        'ingestion_method', 'senate_lis_roll_call_xml',
        'roll_call_source_record_key', 'senate:{congress}:{congress_year}:{roll_call_number}',
        'member_vote_source_record_key', 'senate:{congress}:{congress_year}:{roll_call_number}:{lis_member_id}',
        'rights', jsonb_build_object(
            'classification', 'official_public_information',
            'decision', 'Retain and republish normalized facts with United States Senate attribution and a source link.',
            'checked_at', '2026-07-29'
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
            'label', 'United States Senate',
            'link_required', true,
            'source_url_required', true
        ),
        'health_policy', jsonb_build_object(
            'report_attempts_successes_failures_and_skips', true,
            'publication_lag_is_reported_separately', true,
            'degraded_behavior', 'fail_closed_for_future_senate_writes_and_retain_last_valid_normalized_rows'
        ),
        'disable_path', 'disable_senate_shadow_fetch_or_future_authoritative_writes_without_deleting_catalog_evidence_provenance_or_identity_mappings',
        'production_write_status', 'disabled_pending_separate_ingestion_review'
    );
BEGIN
    -- A recorded marker means this forward-only review has already run. Never
    -- replay it and overwrite a later source retirement or other review choice.
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0028_senate_roll_call_source_review'
    ) THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0027_house_roll_call_production_enablement'
    ) THEN
        RAISE EXCEPTION
            'migration 0027_house_roll_call_production_enablement must be applied first'
            USING ERRCODE = '55000';
    END IF;

    SELECT status, repo_fit
    INTO v_source_status, v_source_repo_fit
    FROM public.source_catalog_sources
    WHERE slug = 'senate-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog row is missing: senate-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT status
    INTO v_endpoint_status
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog endpoint is missing: senate-roll-call-xml.lis-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    -- Reserve the official source-record namespace without making LIS member IDs
    -- an automatic person-identity key. Future person attachment must still cross
    -- through the reviewed LIS-to-Bioguide mapping and one trusted Bioguide owner.
    INSERT INTO public.source_systems (
        key,
        display_name,
        source_kind,
        trust_level,
        verified,
        notes
    )
    VALUES (
        'senate-lis',
        'U.S. Senate Legislative Information System',
        'government',
        'official',
        true,
        'Official Senate roll-call source-record namespace. LIS member IDs require the separately trusted congress-legislators LIS-to-Bioguide crosswalk before canonical attachment.'
    )
    ON CONFLICT (key) DO NOTHING;

    SELECT display_name, source_kind, trust_level, verified
    INTO
        v_source_system_display_name,
        v_source_system_kind,
        v_source_system_trust_level,
        v_source_system_verified
    FROM public.source_systems
    WHERE key = 'senate-lis'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source system is missing: senate-lis'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_system_display_name IS DISTINCT FROM 'U.S. Senate Legislative Information System'
       OR v_source_system_kind IS DISTINCT FROM 'government'
       OR v_source_system_trust_level IS DISTINCT FROM 'official'
       OR v_source_system_verified IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            'senate-lis source system conflicts with the reviewed official namespace: %/%/%/%',
            v_source_system_display_name,
            v_source_system_kind,
            v_source_system_trust_level,
            v_source_system_verified
            USING ERRCODE = '55000';
    END IF;

    PERFORM 1
    FROM public.source_systems
    WHERE key = 'congress-legislators'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required identifier source system is missing: congress-legislators'
            USING ERRCODE = '23503';
    END IF;

    -- Do not silently overwrite an out-of-band maintainer decision. If the live
    -- catalog changed after shadow review, stop for a fresh review instead.
    IF v_source_status IS DISTINCT FROM 'candidate'
       OR v_source_repo_fit IS DISTINCT FROM 'needs_review'
       OR v_endpoint_status IS DISTINCT FROM 'candidate' THEN
        RAISE EXCEPTION
            'Senate roll-call source review expected candidate/needs_review/candidate, found %/%/%',
            v_source_status,
            v_source_repo_fit,
            v_endpoint_status
            USING ERRCODE = '55000';
    END IF;

    PERFORM public.review_source_catalog_source(
        p_source_slug => 'senate-roll-call-xml',
        p_new_status => 'approved',
        p_repo_fit => 'wired',
        p_reviewer => 'phase-4-senate-source-review',
        p_reason => 'Approved for bounded read-only shadow use after two corrected production reconciliations produced complete exact LIS coverage, complete published GovTrack cast agreement, healthy source requests, and no identity or vote conflicts; approval does not enable production writes.',
        p_evidence => v_evidence || jsonb_build_object('review_scope', 'source')
    );

    PERFORM public.review_source_catalog_endpoint(
        p_source_slug => 'senate-roll-call-xml',
        p_endpoint_slug => 'lis-roll-call-feed',
        p_new_status => 'approved',
        p_reviewer => 'phase-4-senate-source-review',
        p_reason => 'Approved for the existing bounded read-only shadow extractor; normalized Senate production writes remain disabled pending a separate provenance and conflict-safe ingestion review.',
        p_evidence => v_evidence || jsonb_build_object('review_scope', 'endpoint')
    );

    UPDATE public.source_catalog_sources
    SET
        verified_at = DATE '2026-07-29',
        notes = 'Official Senate roll-call source approved for bounded read-only shadow use after two corrected production reconciliations. Authoritative/public vote writes remain disabled pending a separate reviewed provenance and ingestion path.',
        metadata = metadata || jsonb_build_object(
            'repo_usage_status', 'Wired as a bounded read-only reconciliation shadow; authoritative writes disabled.',
            'repo_evidence', 'Two corrected production runs produced 4,996 exact LIS joins and 4,996 GovTrack cast matches with zero gaps or conflicts.',
            'repo_next_action', 'Add a conflict-safe Senate provenance and ingestion path in a separate reviewed migration and PR.',
            'source_system_key', 'senate-lis',
            'identity_join_source_system_key', 'congress-legislators',
            'ingestion_status', 'shadow_only',
            'production_write_status', 'disabled_pending_separate_ingestion_review',
            'production_writes_enabled', false,
            'source_review', v_evidence
        )
    WHERE slug = 'senate-roll-call-xml';

    UPDATE public.source_catalog_endpoints
    SET
        notes = 'Approved official endpoint used by the bounded read-only shadow extractor. Production vote writes remain disabled.',
        metadata = metadata || jsonb_build_object(
            'ingestion_status', 'shadow_only',
            'join_policy', 'exact_xml_lis_member_id_via_trusted_lis_to_bioguide_crosswalk',
            'raw_xml_retained', false,
            'production_write_status', 'disabled_pending_separate_ingestion_review',
            'production_writes_enabled', false
        )
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed';

    INSERT INTO public.source_catalog_source_system_links (
        source_slug,
        source_system_key,
        link_type,
        notes
    )
    VALUES
        (
            'senate-roll-call-xml',
            'senate-lis',
            'same_source',
            'Official U.S. Senate LIS roll-call source-record namespace.'
        ),
        (
            'senate-roll-call-xml',
            'congress-legislators',
            'identifier_source',
            'Current shadow resolution uses the trusted active-plus-historical LIS-to-Bioguide crosswalk; it does not attach people by name.'
        )
    ON CONFLICT (source_slug, source_system_key, link_type) DO UPDATE SET
        notes = EXCLUDED.notes;

    INSERT INTO public.schema_migrations (
        migration_key,
        migration_version,
        description,
        metadata
    )
    VALUES (
        '0028_senate_roll_call_source_review',
        28,
        'Approve the official Senate roll-call source for bounded read-only shadow use and record its future-ingestion contract.',
        jsonb_build_object(
            'source_slug', 'senate-roll-call-xml',
            'endpoint_slug', 'lis-roll-call-feed',
            'source_system_key', 'senate-lis',
            'source_status', 'approved',
            'repo_fit', 'wired',
            'ingestion_status', 'shadow_only',
            'production_writes_enabled', false,
            'scraper_preflight_required', false,
            'corrected_shadow_run_ids', v_evidence -> 'corrected_shadow_run_ids'
        )
    );
END
$migration$;

COMMIT;
