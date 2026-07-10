-- 0022_project_stabilization.sql
--
-- Stabilizes the canonical identity bridge before additional person-producing sources
-- are enabled. This migration is intentionally private-by-default: it repairs reviewed
-- identity merges, introduces an applied-migration ledger and source-record/office-term
-- lifecycle backbone, tightens safe identity invariants, and adds canonical role reads.
--
-- The migration is one explicit transaction because the repair uses an ON COMMIT DROP
-- temporary table. A failed initial application is transactionally restartable; after the
-- applied marker is recorded, treat this as forward-only migration history.

BEGIN;

SET LOCAL statement_timeout = '60s';

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- --------------------------------------------------------------------------------------
-- Applied migration ledger
-- --------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.schema_migrations (
    migration_key text PRIMARY KEY,
    migration_version integer NOT NULL,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'schema_migrations_key_not_blank_check'
          AND conrelid = 'public.schema_migrations'::regclass
    ) THEN
        ALTER TABLE public.schema_migrations
            ADD CONSTRAINT schema_migrations_key_not_blank_check
            CHECK (NULLIF(btrim(migration_key), '') IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'schema_migrations_version_positive_check'
          AND conrelid = 'public.schema_migrations'::regclass
    ) THEN
        ALTER TABLE public.schema_migrations
            ADD CONSTRAINT schema_migrations_version_positive_check
            CHECK (migration_version > 0);
    END IF;
END $$;

-- --------------------------------------------------------------------------------------
-- Hard identity invariants and missing FK/join indexes
-- --------------------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_no_self_merge_check'
          AND conrelid = 'public.people'::regclass
    ) THEN
        ALTER TABLE public.people
            ADD CONSTRAINT people_no_self_merge_check
            CHECK (merged_into_person_id IS NULL OR merged_into_person_id <> id)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_merge_status_consistency_check'
          AND conrelid = 'public.people'::regclass
    ) THEN
        ALTER TABLE public.people
            ADD CONSTRAINT people_merge_status_consistency_check
            CHECK (
                (status = 'merged' AND merged_into_person_id IS NOT NULL)
                OR (status <> 'merged' AND merged_into_person_id IS NULL)
            )
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'person_external_ids_value_not_blank_check'
          AND conrelid = 'public.person_external_ids'::regclass
    ) THEN
        ALTER TABLE public.person_external_ids
            ADD CONSTRAINT person_external_ids_value_not_blank_check
            CHECK (
                NULLIF(btrim(source_system_key), '') IS NOT NULL
                AND NULLIF(btrim(external_id_type), '') IS NOT NULL
                AND NULLIF(btrim(external_id), '') IS NOT NULL
            )
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.people
        WHERE merged_into_person_id = id
    ) THEN
        ALTER TABLE public.people VALIDATE CONSTRAINT people_no_self_merge_check;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.people
        WHERE (status = 'merged') IS DISTINCT FROM (merged_into_person_id IS NOT NULL)
    ) THEN
        ALTER TABLE public.people VALIDATE CONSTRAINT people_merge_status_consistency_check;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.person_external_ids
        WHERE NULLIF(btrim(source_system_key), '') IS NULL
           OR NULLIF(btrim(external_id_type), '') IS NULL
           OR NULLIF(btrim(external_id), '') IS NULL
    ) THEN
        ALTER TABLE public.person_external_ids
            VALIDATE CONSTRAINT person_external_ids_value_not_blank_check;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_person_external_ids_source_legacy
    ON public.person_external_ids(source_legacy_politician_id)
    WHERE source_legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_person_names_source_system
    ON public.person_names(source_system_key);
CREATE INDEX IF NOT EXISTS idx_person_names_legacy_profile
    ON public.person_names(legacy_politician_id)
    WHERE legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_candidates_source_legacy
    ON public.identity_resolution_candidates(source_legacy_politician_id)
    WHERE source_legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_candidates_candidate_legacy
    ON public.identity_resolution_candidates(candidate_legacy_politician_id)
    WHERE candidate_legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_candidates_source_person
    ON public.identity_resolution_candidates(source_person_id)
    WHERE source_person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_identity_candidates_candidate_person
    ON public.identity_resolution_candidates(candidate_person_id)
    WHERE candidate_person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_relationships_related_politician
    ON public.relationships(related_politician_id)
    WHERE related_politician_id IS NOT NULL;

-- Older sync_legacy_profile_identity calls could create the same null-pair conflict on
-- every run because the original partial unique index excluded null candidate IDs.
WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                candidate_type,
                source_legacy_politician_id,
                COALESCE(source_person_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(candidate_person_id, '00000000-0000-0000-0000-000000000000'::uuid)
            ORDER BY
                CASE status WHEN 'approved' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,
                updated_at DESC,
                id
        ) AS duplicate_rank
    FROM public.identity_resolution_candidates
    WHERE source_legacy_politician_id IS NOT NULL
      AND candidate_legacy_politician_id IS NULL
)
DELETE FROM public.identity_resolution_candidates AS c
USING ranked AS r
WHERE c.id = r.id
  AND r.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_candidates_null_pair_unique
    ON public.identity_resolution_candidates(
        candidate_type,
        source_legacy_politician_id,
        COALESCE(source_person_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(candidate_person_id, '00000000-0000-0000-0000-000000000000'::uuid)
    )
    WHERE source_legacy_politician_id IS NOT NULL
      AND candidate_legacy_politician_id IS NULL;

-- --------------------------------------------------------------------------------------
-- Canonical spoke repair and deterministic deduplication
-- --------------------------------------------------------------------------------------

UPDATE public.contact_info AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;
UPDATE public.financial_disclosures AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;
UPDATE public.campaign_donors AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;
UPDATE public.voting_records AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;
UPDATE public.unconfirmed_mentions AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;
UPDATE public.relationships AS spoke SET person_id = l.person_id
FROM public.legacy_profile_redirects AS l
JOIN public.people AS pe ON pe.id = l.person_id AND pe.status = 'active'
WHERE spoke.politician_id = l.legacy_politician_id
  AND spoke.person_id IS DISTINCT FROM l.person_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.voting_records
        WHERE person_id IS NOT NULL AND roll_call_id IS NOT NULL
        GROUP BY person_id, roll_call_id
        HAVING count(DISTINCT vote_cast) FILTER (WHERE vote_cast IS NOT NULL) > 1
    ) THEN
        RAISE EXCEPTION
            '0022 cannot deduplicate canonical votes: a person has conflicting vote_cast values for one roll_call_id';
    END IF;
END $$;

WITH ranked AS (
    SELECT
        vr.id,
        row_number() OVER (
            PARTITION BY vr.person_id, vr.roll_call_id
            ORDER BY
                (vr.vote_cast IS NOT NULL) DESC,
                COALESCE(l.legacy_politician_id = l.canonical_politician_id, false) DESC,
                (vr.bill_summary IS NOT NULL) DESC,
                (vr.jurisdiction IS NOT NULL) DESC,
                vr.vote_date DESC,
                vr.id
        ) AS duplicate_rank
    FROM public.voting_records AS vr
    LEFT JOIN public.legacy_profile_redirects AS l
      ON l.legacy_politician_id = vr.politician_id
    WHERE vr.person_id IS NOT NULL
      AND vr.roll_call_id IS NOT NULL
)
DELETE FROM public.voting_records AS vr
USING ranked AS r
WHERE vr.id = r.id
  AND r.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_voting_records_person_roll_call_unique
    ON public.voting_records(person_id, roll_call_id)
    WHERE person_id IS NOT NULL AND roll_call_id IS NOT NULL;

WITH ranked AS (
    SELECT
        um.id,
        row_number() OVER (
            PARTITION BY um.person_id, um.url
            ORDER BY
                length(COALESCE(um.content_summary, '')) DESC,
                (um.sentiment_score IS NOT NULL) DESC,
                um.created_at DESC NULLS LAST,
                um.id
        ) AS duplicate_rank
    FROM public.unconfirmed_mentions AS um
    WHERE um.person_id IS NOT NULL
      AND um.url IS NOT NULL
)
DELETE FROM public.unconfirmed_mentions AS um
USING ranked AS r
WHERE um.id = r.id
  AND r.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_unconfirmed_mentions_person_url_unique
    ON public.unconfirmed_mentions(person_id, url)
    WHERE person_id IS NOT NULL AND url IS NOT NULL;


CREATE UNIQUE INDEX IF NOT EXISTS idx_schema_migrations_version
    ON public.schema_migrations(migration_version);

-- --------------------------------------------------------------------------------------
-- Stable source-record and person-role lifecycle backbone
-- --------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.source_records (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_system_key text NOT NULL REFERENCES public.source_systems(key) ON DELETE RESTRICT,
    source_record_key text NOT NULL,
    record_type text NOT NULL DEFAULT 'person_profile',
    person_id uuid REFERENCES public.people(id) ON DELETE SET NULL,
    legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE SET NULL,
    source_catalog_slug text,
    source_endpoint_slug text,
    source_url text,
    raw_payload_ref text,
    payload_hash text,
    verified_lane text NOT NULL DEFAULT 'unverified',
    record_status text NOT NULL DEFAULT 'active',
    source_updated_at timestamptz,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (source_catalog_slug, source_endpoint_slug)
        REFERENCES public.source_catalog_endpoints(source_slug, endpoint_slug)
        ON DELETE SET NULL,
    UNIQUE (source_system_key, source_record_key)
);

CREATE TABLE IF NOT EXISTS public.person_office_terms (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE RESTRICT,
    source_record_id uuid NOT NULL REFERENCES public.source_records(id) ON DELETE CASCADE,
    source_term_key text NOT NULL DEFAULT 'current-office',
    legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE SET NULL,
    office_title text NOT NULL,
    role_type text NOT NULL DEFAULT 'office',
    organization_name text,
    government_level text,
    government_branch text,
    office_type text,
    jurisdiction text,
    state text,
    district text,
    term_start date,
    term_end date,
    term_status text NOT NULL DEFAULT 'current',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_record_id, source_term_key)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_records_key_not_blank_check'
          AND conrelid = 'public.source_records'::regclass
    ) THEN
        ALTER TABLE public.source_records
            ADD CONSTRAINT source_records_key_not_blank_check
            CHECK (NULLIF(btrim(source_system_key), '') IS NOT NULL
               AND NULLIF(btrim(source_record_key), '') IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_records_catalog_endpoint_pair_check'
          AND conrelid = 'public.source_records'::regclass
    ) THEN
        ALTER TABLE public.source_records
            ADD CONSTRAINT source_records_catalog_endpoint_pair_check
            CHECK (
                (source_catalog_slug IS NULL AND source_endpoint_slug IS NULL)
                OR (source_catalog_slug IS NOT NULL AND source_endpoint_slug IS NOT NULL)
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_records_verified_lane_check'
          AND conrelid = 'public.source_records'::regclass
    ) THEN
        ALTER TABLE public.source_records
            ADD CONSTRAINT source_records_verified_lane_check
            CHECK (verified_lane IN ('verified', 'unverified', 'mixed', 'unknown'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_records_status_check'
          AND conrelid = 'public.source_records'::regclass
    ) THEN
        ALTER TABLE public.source_records
            ADD CONSTRAINT source_records_status_check
            CHECK (record_status IN ('active', 'superseded', 'retired', 'deleted'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_records_seen_order_check'
          AND conrelid = 'public.source_records'::regclass
    ) THEN
        ALTER TABLE public.source_records
            ADD CONSTRAINT source_records_seen_order_check
            CHECK (first_seen_at <= last_seen_at);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'person_office_terms_key_not_blank_check'
          AND conrelid = 'public.person_office_terms'::regclass
    ) THEN
        ALTER TABLE public.person_office_terms
            ADD CONSTRAINT person_office_terms_key_not_blank_check
            CHECK (NULLIF(btrim(source_term_key), '') IS NOT NULL
               AND NULLIF(btrim(office_title), '') IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'person_office_terms_status_check'
          AND conrelid = 'public.person_office_terms'::regclass
    ) THEN
        ALTER TABLE public.person_office_terms
            ADD CONSTRAINT person_office_terms_status_check
            CHECK (term_status IN ('current', 'historical', 'future', 'unknown', 'retracted'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'person_office_terms_date_order_check'
          AND conrelid = 'public.person_office_terms'::regclass
    ) THEN
        ALTER TABLE public.person_office_terms
            ADD CONSTRAINT person_office_terms_date_order_check
            CHECK (term_start IS NULL OR term_end IS NULL OR term_start <= term_end);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_records_person
    ON public.source_records(person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_records_legacy_profile
    ON public.source_records(legacy_politician_id) WHERE legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_records_catalog_endpoint
    ON public.source_records(source_catalog_slug, source_endpoint_slug)
    WHERE source_catalog_slug IS NOT NULL AND source_endpoint_slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_source_records_status_last_seen
    ON public.source_records(record_status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_person_office_terms_person_status_start
    ON public.person_office_terms(person_id, term_status, term_start DESC NULLS LAST, id);
CREATE INDEX IF NOT EXISTS idx_person_office_terms_legacy_profile
    ON public.person_office_terms(legacy_politician_id)
    WHERE legacy_politician_id IS NOT NULL;

DROP TRIGGER IF EXISTS source_records_set_updated_at ON public.source_records;
CREATE TRIGGER source_records_set_updated_at
    BEFORE UPDATE ON public.source_records
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS person_office_terms_set_updated_at ON public.person_office_terms;
CREATE TRIGGER person_office_terms_set_updated_at
    BEFORE UPDATE ON public.person_office_terms
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- --------------------------------------------------------------------------------------
-- Source-catalog corrections that preserve subsequent maintainer review decisions
-- --------------------------------------------------------------------------------------

UPDATE public.source_catalog_endpoints
SET
    access_level = 'free_key',
    auth_type = 'api_key',
    credential_provider = 'openstates',
    notes = CASE
        WHEN notes ILIKE '%requires an OpenStates API key%' THEN notes
        ELSE concat_ws(' ', notes, 'Requires an OpenStates API key.')
    END
WHERE source_slug = 'openstates'
  AND endpoint_slug = 'api-v3';

UPDATE public.source_catalog_sources
SET
    access_level = 'free_key',
    auth_type = 'api_key',
    credential_provider = 'openstates',
    notes = CASE
        WHEN notes ILIKE '%API v3%require%API key%' THEN notes
        ELSE concat_ws(' ', notes, 'OpenStates API v3 requires an API key; the people tarball remains keyless.')
    END
WHERE slug = 'openstates';

WITH corrected AS (
    UPDATE public.source_catalog_sources AS s
    SET
        status = 'candidate',
        repo_fit = 'candidate',
        notes = CASE
            WHEN s.notes ILIKE '%no extractor%' THEN s.notes
            ELSE concat_ws(' ', s.notes, 'No Federal Judicial Center extractor exists yet.')
        END
    WHERE s.slug = 'fjc'
      AND s.status = 'approved'
      AND s.repo_fit = 'wired'
      AND NOT EXISTS (
          SELECT 1
          FROM public.source_catalog_review_events AS e
          WHERE e.source_slug = s.slug
            AND e.endpoint_slug IS NULL
      )
    RETURNING s.slug
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
    corrected.slug,
    'approved',
    'candidate',
    'migration-0022',
    'Corrected catalog status: FJC is reserved but has no wired extractor.',
    jsonb_build_object(
        'migration', '0022_project_stabilization',
        'previous_repo_fit', 'wired',
        'new_repo_fit', 'candidate'
    )
FROM corrected;

-- --------------------------------------------------------------------------------------
-- Private validation reports and canonical public role read
-- --------------------------------------------------------------------------------------

CREATE OR REPLACE VIEW public.identity_validation_invalid_merge_state AS
SELECT
    pe.id AS person_id,
    pe.status,
    pe.merged_into_person_id,
    target.status AS target_status,
    target.merged_into_person_id AS target_merged_into_person_id,
    CASE
        WHEN pe.merged_into_person_id = pe.id THEN 'self_merge'
        WHEN (pe.status = 'merged') IS DISTINCT FROM (pe.merged_into_person_id IS NOT NULL)
            THEN 'status_target_mismatch'
        WHEN pe.status = 'merged' AND target.id IS NULL THEN 'missing_merge_target'
        WHEN pe.status = 'merged' AND target.status <> 'active' THEN 'merge_target_not_active'
        ELSE 'unknown'
    END AS violation
FROM public.people AS pe
LEFT JOIN public.people AS target ON target.id = pe.merged_into_person_id
WHERE pe.merged_into_person_id = pe.id
   OR (pe.status = 'merged') IS DISTINCT FROM (pe.merged_into_person_id IS NOT NULL)
   OR (pe.status = 'merged' AND (target.id IS NULL OR target.status <> 'active'));

CREATE OR REPLACE VIEW public.identity_validation_redirect_person_status AS
SELECT
    l.legacy_politician_id,
    l.person_id,
    pe.status AS person_status,
    pe.merged_into_person_id,
    l.canonical_politician_id,
    l.resolution_method
FROM public.legacy_profile_redirects AS l
LEFT JOIN public.people AS pe ON pe.id = l.person_id
WHERE pe.id IS NULL OR pe.status <> 'active';

CREATE OR REPLACE VIEW public.identity_validation_spoke_person_mismatch AS
SELECT 'contact_info'::text AS table_name, ci.politician_id, ci.politician_id::text AS row_key,
       ci.person_id AS stored_person_id, l.person_id AS redirect_person_id
FROM public.contact_info AS ci
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = ci.politician_id
WHERE ci.person_id IS DISTINCT FROM l.person_id
UNION ALL
SELECT 'financial_disclosures', fd.politician_id, fd.id::text, fd.person_id, l.person_id
FROM public.financial_disclosures AS fd
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = fd.politician_id
WHERE fd.person_id IS DISTINCT FROM l.person_id
UNION ALL
SELECT 'campaign_donors', cd.politician_id, cd.id::text, cd.person_id, l.person_id
FROM public.campaign_donors AS cd
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = cd.politician_id
WHERE cd.person_id IS DISTINCT FROM l.person_id
UNION ALL
SELECT 'voting_records', vr.politician_id, vr.id::text, vr.person_id, l.person_id
FROM public.voting_records AS vr
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = vr.politician_id
WHERE vr.person_id IS DISTINCT FROM l.person_id
UNION ALL
SELECT 'unconfirmed_mentions', um.politician_id, um.id::text, um.person_id, l.person_id
FROM public.unconfirmed_mentions AS um
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = um.politician_id
WHERE um.person_id IS DISTINCT FROM l.person_id
UNION ALL
SELECT 'relationships', rel.politician_id, rel.id::text, rel.person_id, l.person_id
FROM public.relationships AS rel
JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = rel.politician_id
WHERE rel.person_id IS DISTINCT FROM l.person_id;

CREATE OR REPLACE VIEW public.source_record_validation_identity_mismatch AS
SELECT
    sr.id AS source_record_id,
    sr.source_system_key,
    sr.source_record_key,
    sr.person_id AS source_record_person_id,
    sr.legacy_politician_id,
    l.person_id AS redirect_person_id
FROM public.source_records AS sr
JOIN public.legacy_profile_redirects AS l
  ON l.legacy_politician_id = sr.legacy_politician_id
WHERE sr.person_id IS DISTINCT FROM l.person_id;

CREATE OR REPLACE VIEW public.source_record_validation_lifecycle_mismatch AS
SELECT
    sr.id AS source_record_id,
    sr.person_id,
    sr.source_system_key,
    sr.source_record_key,
    sr.record_status,
    term.id AS office_term_id,
    term.source_term_key,
    term.term_status
FROM public.source_records AS sr
JOIN public.person_office_terms AS term ON term.source_record_id = sr.id
WHERE sr.record_status <> 'active'
  AND term.term_status = 'current';

CREATE OR REPLACE FUNCTION public.get_canonical_person_office_terms(p_id uuid)
RETURNS TABLE (
    id uuid,
    person_id uuid,
    source_record_id uuid,
    source_system_key text,
    source_record_key text,
    source_url text,
    office_title text,
    role_type text,
    organization_name text,
    government_level text,
    government_branch text,
    office_type text,
    jurisdiction text,
    state text,
    district text,
    term_start date,
    term_end date,
    term_status text,
    verified_lane text,
    last_seen_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH resolved AS (
        SELECT legacy.person_id
        FROM public.get_canonical_person_legacy_ids(p_id) AS legacy
        LIMIT 1
    )
    SELECT
        term.id,
        term.person_id,
        term.source_record_id,
        source.source_system_key,
        source.source_record_key,
        source.source_url,
        term.office_title,
        term.role_type,
        term.organization_name,
        term.government_level,
        term.government_branch,
        term.office_type,
        term.jurisdiction,
        term.state,
        term.district,
        term.term_start,
        term.term_end,
        term.term_status,
        source.verified_lane,
        source.last_seen_at
    FROM resolved
    JOIN public.person_office_terms AS term ON term.person_id = resolved.person_id
    JOIN public.source_records AS source ON source.id = term.source_record_id
    WHERE term.term_status <> 'retracted'
      AND source.record_status <> 'deleted'
      AND (source.record_status = 'active' OR term.term_status <> 'current')
    ORDER BY
        (term.term_status = 'current') DESC,
        term.term_start DESC NULLS LAST,
        term.term_end DESC NULLS LAST,
        term.office_title,
        term.id;
$$;

-- --------------------------------------------------------------------------------------
-- RLS, least-privilege grants, and applied marker
-- --------------------------------------------------------------------------------------

ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.person_office_terms ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.schema_migrations FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_records FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.person_office_terms FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE public.schema_migrations TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.source_records TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.person_office_terms TO service_role;

REVOKE ALL ON TABLE public.identity_validation_invalid_merge_state
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.identity_validation_redirect_person_status
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.identity_validation_spoke_person_mismatch
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_record_validation_identity_mismatch
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.source_record_validation_lifecycle_mismatch
    FROM PUBLIC, anon, authenticated;

GRANT SELECT ON TABLE public.identity_validation_invalid_merge_state TO service_role;
GRANT SELECT ON TABLE public.identity_validation_redirect_person_status TO service_role;
GRANT SELECT ON TABLE public.identity_validation_spoke_person_mismatch TO service_role;
GRANT SELECT ON TABLE public.source_record_validation_identity_mismatch TO service_role;
GRANT SELECT ON TABLE public.source_record_validation_lifecycle_mismatch TO service_role;

REVOKE EXECUTE ON FUNCTION public.get_canonical_person_office_terms(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_canonical_person_office_terms(uuid) TO anon, authenticated;

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0022_project_stabilization',
    22,
    'Canonical identity, source-record, role, and migration-safety stabilization.',
    jsonb_build_object(
        'identity_repair', true,
        'source_records', true,
        'person_office_terms', true
    )
)
ON CONFLICT (migration_key) DO UPDATE SET
    description = EXCLUDED.description,
    metadata = public.schema_migrations.metadata || EXCLUDED.metadata;

-- Maintainer validation after application (all should return zero rows):
-- SELECT * FROM public.identity_validation_invalid_merge_state;
-- SELECT * FROM public.identity_validation_redirect_person_status;
-- SELECT * FROM public.identity_validation_spoke_person_mismatch;
-- SELECT * FROM public.source_record_validation_identity_mismatch;
-- SELECT * FROM public.source_record_validation_lifecycle_mismatch;

-- --------------------------------------------------------------------------------------
-- Forward repair for approved migration-0015 merges after an older 0011 rerun
-- --------------------------------------------------------------------------------------

DROP TABLE IF EXISTS _0022_openstates_federal_merge_repair;

CREATE TEMP TABLE _0022_openstates_federal_merge_repair
ON COMMIT DROP
AS
WITH observer_candidates AS (
    SELECT
        c.id AS candidate_id,
        c.source_legacy_politician_id AS stale_legacy_politician_id,
        c.source_person_id AS stale_person_id,
        c.evidence -> 'matching_person_ids' AS matching_person_ids,
        max(k.value ->> 'external_id') FILTER (
            WHERE k.value ->> 'source_system_key' = 'bioguide'
              AND k.value ->> 'external_id_type' = 'bioguide_id'
        ) AS bioguide_id,
        max(k.value ->> 'external_id') FILTER (
            WHERE k.value ->> 'source_system_key' = 'openstates'
              AND k.value ->> 'external_id_type' = 'openstates_person_id'
        ) AS openstates_person_id
    FROM public.identity_resolution_candidates AS c
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE
            WHEN jsonb_typeof(c.evidence -> 'deterministic_keys') = 'array'
                THEN c.evidence -> 'deterministic_keys'
            ELSE '[]'::jsonb
        END
    ) AS k(value)
    WHERE c.candidate_type = 'identity_observer_blocked_deterministic_keys_match_multiple_people'
      AND c.status IN ('approved', 'pending')
      AND c.source_legacy_politician_id = c.candidate_legacy_politician_id
      AND c.source_person_id IS NOT NULL
    GROUP BY
        c.id,
        c.source_legacy_politician_id,
        c.source_person_id,
        c.evidence -> 'matching_person_ids'
),
repair_targets AS (
    SELECT
        oc.candidate_id,
        oc.stale_legacy_politician_id,
        oc.stale_person_id,
        survivor.person_id AS survivor_person_id,
        survivor.source_legacy_politician_id AS survivor_legacy_politician_id,
        survivor_redirect.canonical_politician_id AS survivor_canonical_politician_id,
        oc.bioguide_id,
        oc.openstates_person_id
    FROM observer_candidates AS oc
    JOIN public.politicians AS stale_profile
      ON stale_profile.id = oc.stale_legacy_politician_id
     AND (
         stale_profile.current_office LIKE 'State Representative from US District%'
         OR stale_profile.current_office LIKE 'State Senator from US District%'
     )
    JOIN public.legacy_profile_redirects AS stale_redirect
      ON stale_redirect.legacy_politician_id = oc.stale_legacy_politician_id
     AND stale_redirect.person_id = oc.stale_person_id
    JOIN public.people AS stale_person
      ON stale_person.id = oc.stale_person_id
     AND stale_person.status IN ('active', 'merged')
    JOIN public.person_external_ids AS stale_openstates
      ON stale_openstates.person_id = oc.stale_person_id
     AND stale_openstates.source_system_key = 'openstates'
     AND stale_openstates.external_id_type = 'openstates_person_id'
     AND stale_openstates.external_id = oc.openstates_person_id
    JOIN public.person_external_ids AS survivor
      ON survivor.source_system_key = 'bioguide'
     AND survivor.external_id_type = 'bioguide_id'
     AND survivor.external_id = oc.bioguide_id
     AND survivor.person_id <> oc.stale_person_id
    JOIN public.people AS survivor_person
      ON survivor_person.id = survivor.person_id
     AND survivor_person.status = 'active'
    JOIN public.legacy_profile_redirects AS survivor_redirect
      ON survivor_redirect.legacy_politician_id = survivor.source_legacy_politician_id
    WHERE oc.bioguide_id IS NOT NULL
      AND oc.openstates_person_id IS NOT NULL
      AND (
          stale_person.status = 'active'
          OR stale_person.merged_into_person_id = survivor.person_id
      )
      AND COALESCE(oc.matching_person_ids, '[]'::jsonb) ? oc.stale_person_id::text
      AND COALESCE(oc.matching_person_ids, '[]'::jsonb) ? survivor.person_id::text
)
SELECT DISTINCT ON (candidate_id)
    candidate_id,
    stale_legacy_politician_id,
    stale_person_id,
    survivor_person_id,
    survivor_legacy_politician_id,
    survivor_canonical_politician_id,
    bioguide_id,
    openstates_person_id
FROM repair_targets
ORDER BY candidate_id, survivor_person_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM _0022_openstates_federal_merge_repair
        GROUP BY stale_person_id
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION '0022 repair found a stale person mapped to multiple survivors';
    END IF;
END $$;

INSERT INTO public.person_merge_events (
    survivor_person_id,
    merged_person_id,
    reason,
    evidence
)
SELECT
    t.survivor_person_id,
    t.stale_person_id,
    'openstates_data_us_federal_duplicate_cleanup',
    jsonb_build_object(
        'migration', '0022_project_stabilization',
        'repair_of', '0015_openstates_federal_duplicate_cleanup',
        'identity_resolution_candidate_id', t.candidate_id,
        'stale_legacy_politician_id', t.stale_legacy_politician_id,
        'survivor_legacy_politician_id', t.survivor_legacy_politician_id
    )
FROM _0022_openstates_federal_merge_repair AS t
WHERE NOT EXISTS (
    SELECT 1
    FROM public.person_merge_events AS e
    WHERE e.survivor_person_id = t.survivor_person_id
      AND e.merged_person_id = t.stale_person_id
      AND e.reason = 'openstates_data_us_federal_duplicate_cleanup'
);

INSERT INTO public.person_external_ids (
    person_id,
    source_system_key,
    external_id_type,
    external_id,
    is_trusted,
    source_legacy_politician_id
)
SELECT
    t.survivor_person_id,
    pei.source_system_key,
    pei.external_id_type,
    pei.external_id,
    pei.is_trusted,
    pei.source_legacy_politician_id
FROM public.person_external_ids AS pei
JOIN _0022_openstates_federal_merge_repair AS t ON t.stale_person_id = pei.person_id
ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
    person_id = EXCLUDED.person_id,
    is_trusted = public.person_external_ids.is_trusted OR EXCLUDED.is_trusted,
    source_legacy_politician_id = COALESCE(
        EXCLUDED.source_legacy_politician_id,
        public.person_external_ids.source_legacy_politician_id
    );

INSERT INTO public.person_names (
    person_id,
    source_system_key,
    legacy_politician_id,
    name_text,
    normalized_name,
    name_type,
    is_primary
)
SELECT
    t.survivor_person_id,
    pn.source_system_key,
    pn.legacy_politician_id,
    pn.name_text,
    pn.normalized_name,
    pn.name_type,
    false
FROM public.person_names AS pn
JOIN _0022_openstates_federal_merge_repair AS t ON t.stale_person_id = pn.person_id
ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO UPDATE SET
    is_primary = public.person_names.is_primary OR EXCLUDED.is_primary;

DELETE FROM public.person_names AS pn
USING _0022_openstates_federal_merge_repair AS t
WHERE pn.person_id = t.stale_person_id;

UPDATE public.legacy_profile_redirects AS l
SET
    person_id = t.survivor_person_id,
    canonical_politician_id = t.survivor_canonical_politician_id,
    resolution_method = 'openstates_data_us_federal_duplicate_cleanup',
    confidence = 1.000
FROM _0022_openstates_federal_merge_repair AS t
WHERE l.person_id = t.stale_person_id
   OR l.legacy_politician_id = t.stale_legacy_politician_id;

-- Remove only the known-bad data/us compatibility profile's spokes. If a stale person
-- owned any additional reviewed aliases, preserve their facts and reparent them.
DELETE FROM public.contact_info AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;
UPDATE public.contact_info AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

DELETE FROM public.financial_disclosures AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;
UPDATE public.financial_disclosures AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

DELETE FROM public.campaign_donors AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;
UPDATE public.campaign_donors AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

DELETE FROM public.voting_records AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM _0022_openstates_federal_merge_repair AS t
        JOIN public.voting_records AS stale_vote
          ON stale_vote.person_id = t.stale_person_id
        JOIN public.voting_records AS survivor_vote
          ON survivor_vote.person_id = t.survivor_person_id
         AND survivor_vote.roll_call_id = stale_vote.roll_call_id
        WHERE stale_vote.roll_call_id IS NOT NULL
          AND stale_vote.vote_cast IS NOT NULL
          AND survivor_vote.vote_cast IS NOT NULL
          AND stale_vote.vote_cast IS DISTINCT FROM survivor_vote.vote_cast
    ) THEN
        RAISE EXCEPTION '0022 merge repair found conflicting votes for the same canonical roll call';
    END IF;
END $$;

-- The canonical unique index may already exist on a restart. Remove an exact-key stale
-- row before reparenting when the survivor already owns that roll call.
DELETE FROM public.voting_records AS stale_vote
USING _0022_openstates_federal_merge_repair AS t,
      public.voting_records AS survivor_vote
WHERE stale_vote.person_id = t.stale_person_id
  AND survivor_vote.person_id = t.survivor_person_id
  AND survivor_vote.roll_call_id = stale_vote.roll_call_id
  AND stale_vote.roll_call_id IS NOT NULL
  AND survivor_vote.id <> stale_vote.id;

UPDATE public.voting_records AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

DELETE FROM public.unconfirmed_mentions AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;

DELETE FROM public.unconfirmed_mentions AS stale_mention
USING _0022_openstates_federal_merge_repair AS t,
      public.unconfirmed_mentions AS survivor_mention
WHERE stale_mention.person_id = t.stale_person_id
  AND survivor_mention.person_id = t.survivor_person_id
  AND survivor_mention.url = stale_mention.url
  AND stale_mention.url IS NOT NULL
  AND survivor_mention.id <> stale_mention.id;

UPDATE public.unconfirmed_mentions AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

DELETE FROM public.relationships AS spoke
USING _0022_openstates_federal_merge_repair AS t
WHERE spoke.politician_id = t.stale_legacy_politician_id;
UPDATE public.relationships AS spoke SET person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t WHERE spoke.person_id = t.stale_person_id;

UPDATE public.people AS pe
SET status = 'merged', merged_into_person_id = t.survivor_person_id
FROM _0022_openstates_federal_merge_repair AS t
WHERE pe.id = t.stale_person_id;

UPDATE public.identity_resolution_candidates AS c
SET
    status = 'approved',
    candidate_person_id = t.survivor_person_id,
    score = 1.000,
    evidence = c.evidence || jsonb_build_object(
        'stabilization_repair',
        jsonb_build_object(
            'migration', '0022_project_stabilization',
            'repaired_at', now(),
            'stale_person_id', t.stale_person_id,
            'survivor_person_id', t.survivor_person_id
        )
    )
FROM _0022_openstates_federal_merge_repair AS t
WHERE c.id = t.candidate_id;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM _0022_openstates_federal_merge_repair AS t
        JOIN public.legacy_profile_redirects AS l ON l.person_id = t.stale_person_id
    ) OR EXISTS (
        SELECT 1
        FROM _0022_openstates_federal_merge_repair AS t
        JOIN public.person_external_ids AS pei ON pei.person_id = t.stale_person_id
    ) THEN
        RAISE EXCEPTION '0022 repair left redirects or external IDs on a merged stale person';
    END IF;
END $$;

-- Flatten any pre-existing acyclic merge chains, then reject new chains at write time.
DO $$
DECLARE
    changed_rows integer;
BEGIN
    IF EXISTS (
        WITH RECURSIVE walk(root_id, current_id, path, cycle) AS (
            SELECT
                pe.id,
                pe.merged_into_person_id,
                ARRAY[pe.id],
                pe.merged_into_person_id = pe.id
            FROM public.people AS pe
            WHERE pe.status = 'merged'

            UNION ALL

            SELECT
                walk.root_id,
                target.merged_into_person_id,
                walk.path || target.id,
                target.id = ANY(walk.path)
            FROM walk
            JOIN public.people AS target ON target.id = walk.current_id
            WHERE walk.current_id IS NOT NULL
              AND NOT walk.cycle
        )
        SELECT 1 FROM walk WHERE cycle
    ) THEN
        RAISE EXCEPTION '0022 found a cycle in people.merged_into_person_id; manual review is required';
    END IF;

    LOOP
        UPDATE public.people AS child
        SET merged_into_person_id = parent.merged_into_person_id
        FROM public.people AS parent
        WHERE child.status = 'merged'
          AND parent.id = child.merged_into_person_id
          AND parent.status = 'merged'
          AND parent.merged_into_person_id IS NOT NULL;

        GET DIAGNOSTICS changed_rows = ROW_COUNT;
        EXIT WHEN changed_rows = 0;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM public.people AS child
        LEFT JOIN public.people AS target ON target.id = child.merged_into_person_id
        WHERE child.status = 'merged'
          AND (target.id IS NULL OR target.status <> 'active' OR target.merged_into_person_id IS NOT NULL)
    ) THEN
        RAISE EXCEPTION '0022 found a merged person whose final survivor is not active';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.enforce_people_merge_target()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    target_status text;
    target_merged_into uuid;
BEGIN
    IF NEW.status <> 'active' AND EXISTS (
        SELECT 1
        FROM public.people AS child
        WHERE child.merged_into_person_id = NEW.id
          AND child.id <> NEW.id
    ) THEN
        RAISE EXCEPTION 'person % is an active merge survivor; reparent its children first', NEW.id;
    END IF;

    IF NEW.status = 'merged' THEN
        IF NEW.merged_into_person_id IS NULL OR NEW.merged_into_person_id = NEW.id THEN
            RAISE EXCEPTION 'merged people require a different survivor person';
        END IF;

        SELECT pe.status, pe.merged_into_person_id
        INTO target_status, target_merged_into
        FROM public.people AS pe
        WHERE pe.id = NEW.merged_into_person_id
        FOR UPDATE;

        IF target_status IS DISTINCT FROM 'active' OR target_merged_into IS NOT NULL THEN
            RAISE EXCEPTION 'merge survivor % must be active and unmerged', NEW.merged_into_person_id;
        END IF;

    ELSIF NEW.merged_into_person_id IS NOT NULL THEN
        RAISE EXCEPTION 'only merged people may have merged_into_person_id';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS people_enforce_merge_target ON public.people;
CREATE TRIGGER people_enforce_merge_target
    BEFORE INSERT OR UPDATE OF status, merged_into_person_id ON public.people
    FOR EACH ROW EXECUTE FUNCTION public.enforce_people_merge_target();

REVOKE EXECUTE ON FUNCTION public.enforce_people_merge_target() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.people
        WHERE merged_into_person_id = id
           OR (status = 'merged') IS DISTINCT FROM (merged_into_person_id IS NOT NULL)
    ) THEN
        RAISE EXCEPTION '0022 cannot finalize: invalid people merge status remains';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.person_external_ids
        WHERE NULLIF(btrim(source_system_key), '') IS NULL
           OR NULLIF(btrim(external_id_type), '') IS NULL
           OR NULLIF(btrim(external_id), '') IS NULL
    ) THEN
        RAISE EXCEPTION '0022 cannot finalize: blank canonical external identity keys remain';
    END IF;

    ALTER TABLE public.people VALIDATE CONSTRAINT people_no_self_merge_check;
    ALTER TABLE public.people VALIDATE CONSTRAINT people_merge_status_consistency_check;
    ALTER TABLE public.person_external_ids
        VALIDATE CONSTRAINT person_external_ids_value_not_blank_check;
END $$;

-- Include OpenStates/contributed JSON Bioguide crosswalks in the same deterministic
-- namespace used by the Python resolver. The top-level bioguide_id remains preferred.
CREATE OR REPLACE FUNCTION public.get_legacy_profile_identity_keys(p_politician_id uuid)
RETURNS TABLE (
    source_system_key text,
    external_id_type text,
    external_id text,
    priority integer
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH p AS (
        SELECT bioguide_id, external_ids
        FROM public.politicians
        WHERE id = p_politician_id
    )
    SELECT 'bioguide', 'bioguide_id', btrim(p.bioguide_id), 10
    FROM p
    WHERE NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL

    UNION ALL

    SELECT 'bioguide', 'bioguide_id', btrim(p.external_ids ->> 'bioguide'), 11
    FROM p
    WHERE NULLIF(btrim(coalesce(p.external_ids ->> 'bioguide', '')), '') IS NOT NULL

    UNION ALL

    SELECT 'openstates', 'openstates_person_id', btrim(p.external_ids ->> 'openstates'), 20
    FROM p
    WHERE NULLIF(btrim(coalesce(p.external_ids ->> 'openstates', '')), '') IS NOT NULL

    UNION ALL

    SELECT 'govtrack', 'govtrack_person_id', btrim(p.external_ids ->> 'govtrack'), 30
    FROM p
    WHERE NULLIF(btrim(coalesce(p.external_ids ->> 'govtrack', '')), '') IS NOT NULL

    UNION ALL

    SELECT 'wikidata', 'wikidata_qid', btrim(p.external_ids ->> 'wikidata'), 40
    FROM p
    WHERE NULLIF(btrim(coalesce(p.external_ids ->> 'wikidata', '')), '') IS NOT NULL

    UNION ALL

    SELECT 'fec', 'fec_candidate_id', btrim(fec.value), 50
    FROM p
    CROSS JOIN LATERAL jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(p.external_ids -> 'fec') = 'array'
            THEN p.external_ids -> 'fec' ELSE '[]'::jsonb END
    ) AS fec(value)
    WHERE NULLIF(btrim(fec.value), '') IS NOT NULL

    UNION ALL

    SELECT 'fec', 'fec_candidate_id', btrim(p.external_ids ->> 'fec'), 50
    FROM p
    WHERE jsonb_typeof(p.external_ids -> 'fec') IN ('string', 'number')
      AND NULLIF(btrim(coalesce(p.external_ids ->> 'fec', '')), '') IS NOT NULL

    UNION ALL

    SELECT 'fjc', 'fjc_judge_id', btrim(p.external_ids ->> 'fjc'), 60
    FROM p
    WHERE NULLIF(btrim(coalesce(p.external_ids ->> 'fjc', '')), '') IS NOT NULL;
$$;

-- Atomic source-profile ingestion contract. All deterministic conflicts are checked while
-- advisory locks are held and before the compatibility politician row is changed.
CREATE OR REPLACE FUNCTION public.upsert_source_profile_identity(
    p_source_system_key text,
    p_source_record_key text,
    p_profile jsonb,
    p_trusted_external_ids jsonb DEFAULT '[]'::jsonb,
    p_source_url text DEFAULT NULL,
    p_raw_payload_ref text DEFAULT NULL,
    p_payload_hash text DEFAULT NULL,
    p_verified_lane text DEFAULT 'unverified',
    p_office_term jsonb DEFAULT NULL,
    p_source_catalog_slug text DEFAULT NULL,
    p_source_endpoint_slug text DEFAULT NULL,
    p_source_updated_at timestamptz DEFAULT NULL
)
RETURNS TABLE (
    person_id uuid,
    legacy_politician_id uuid,
    source_record_id uuid,
    office_term_id uuid,
    resolution_action text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
#variable_conflict use_column
DECLARE
    v_source_key text := NULLIF(btrim(p_source_system_key), '');
    v_record_key text := NULLIF(btrim(p_source_record_key), '');
    v_full_name text;
    v_bioguide_id text;
    v_external_ids jsonb;
    v_aliases text[] := ARRAY[]::text[];
    v_source_record_id uuid;
    v_existing_source_person_id uuid;
    v_existing_legacy_id uuid;
    v_matching_person_ids uuid[];
    v_target_person_id uuid;
    v_redirect_person_id uuid;
    v_resolved_redirect_person_id uuid;
    v_legacy_id uuid;
    v_synced_person_id uuid;
    v_canonical_legacy_id uuid;
    v_office_term_id uuid;
    v_resolution_action text;
    v_missing_keys jsonb;
    v_candidate_count integer;
BEGIN
    -- Non-mutating schema-preflight probe.
    IF v_source_key = '__preflight__'
       AND v_record_key = '__preflight__'
       AND COALESCE(p_profile ->> 'preflight', '') = 'true' THEN
        RETURN QUERY SELECT NULL::uuid, NULL::uuid, NULL::uuid, NULL::uuid, 'preflight_ok'::text;
        RETURN;
    END IF;

    IF v_source_key IS NULL OR v_record_key IS NULL THEN
        RAISE EXCEPTION 'source_system_key and source_record_key are required'
            USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(p_profile) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'profile must be a JSON object' USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(COALESCE(p_trusted_external_ids, '[]'::jsonb)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'trusted_external_ids must be a JSON array' USING ERRCODE = '22023';
    END IF;

    v_full_name := NULLIF(btrim(p_profile ->> 'full_name'), '');
    IF v_full_name IS NULL THEN
        RAISE EXCEPTION 'profile.full_name is required' USING ERRCODE = '22023';
    END IF;

    IF p_verified_lane NOT IN ('verified', 'unverified', 'mixed', 'unknown') THEN
        RAISE EXCEPTION 'invalid verified_lane: %', p_verified_lane USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.source_systems AS ss WHERE ss.key = v_source_key) THEN
        RAISE EXCEPTION 'unknown source system: %', v_source_key USING ERRCODE = '23503';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
        LEFT JOIN public.source_systems AS ss ON ss.key = NULLIF(btrim(item.value ->> 'source_system_key'), '')
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'source_system_key'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'external_id_type'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'external_id'), '') IS NULL
           OR ss.key IS NULL
           OR NOT ss.verified
           OR (btrim(item.value ->> 'source_system_key'), btrim(item.value ->> 'external_id_type')) NOT IN (
               ('bioguide', 'bioguide_id'),
               ('openstates', 'openstates_person_id'),
               ('govtrack', 'govtrack_person_id'),
               ('wikidata', 'wikidata_qid'),
               ('fec', 'fec_candidate_id'),
               ('fjc', 'fjc_judge_id')
           )
    ) THEN
        RAISE EXCEPTION 'trusted_external_ids contains an invalid, unverified, or unsupported identity key'
            USING ERRCODE = '22023';
    END IF;

    IF (p_source_catalog_slug IS NULL) IS DISTINCT FROM (p_source_endpoint_slug IS NULL) THEN
        RAISE EXCEPTION 'source catalog slug and endpoint slug must be supplied together'
            USING ERRCODE = '22023';
    END IF;

    IF p_source_catalog_slug IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_endpoints AS endpoint
        WHERE endpoint.source_slug = p_source_catalog_slug
          AND endpoint.endpoint_slug = p_source_endpoint_slug
    ) THEN
        RAISE EXCEPTION 'unknown source catalog endpoint: %.%', p_source_catalog_slug, p_source_endpoint_slug
            USING ERRCODE = '23503';
    END IF;

    v_bioguide_id := NULLIF(btrim(p_profile ->> 'bioguide_id'), '');
    v_external_ids := CASE
        WHEN jsonb_typeof(p_profile -> 'external_ids') = 'object'
            THEN jsonb_strip_nulls(p_profile -> 'external_ids')
        ELSE '{}'::jsonb
    END;

    IF jsonb_typeof(p_profile -> 'aliases') = 'array' THEN
        SELECT COALESCE(array_agg(DISTINCT btrim(alias) ORDER BY btrim(alias)), ARRAY[]::text[])
        INTO v_aliases
        FROM jsonb_array_elements_text(p_profile -> 'aliases') AS names(alias)
        WHERE NULLIF(btrim(alias), '') IS NOT NULL;
    END IF;

    -- Every identity-bearing legacy field must be explicitly vouched for by the caller.
    WITH profile_keys(source_system_key, external_id_type, external_id) AS (
        SELECT 'bioguide', 'bioguide_id', v_bioguide_id WHERE v_bioguide_id IS NOT NULL
        UNION
        SELECT 'bioguide', 'bioguide_id', NULLIF(btrim(v_external_ids ->> 'bioguide'), '')
        WHERE NULLIF(btrim(v_external_ids ->> 'bioguide'), '') IS NOT NULL
        UNION
        SELECT 'openstates', 'openstates_person_id', NULLIF(btrim(v_external_ids ->> 'openstates'), '')
        WHERE NULLIF(btrim(v_external_ids ->> 'openstates'), '') IS NOT NULL
        UNION
        SELECT 'govtrack', 'govtrack_person_id', NULLIF(btrim(v_external_ids ->> 'govtrack'), '')
        WHERE NULLIF(btrim(v_external_ids ->> 'govtrack'), '') IS NOT NULL
        UNION
        SELECT 'wikidata', 'wikidata_qid', NULLIF(btrim(v_external_ids ->> 'wikidata'), '')
        WHERE NULLIF(btrim(v_external_ids ->> 'wikidata'), '') IS NOT NULL
        UNION
        SELECT 'fjc', 'fjc_judge_id', NULLIF(btrim(v_external_ids ->> 'fjc'), '')
        WHERE NULLIF(btrim(v_external_ids ->> 'fjc'), '') IS NOT NULL
        UNION
        SELECT 'fec', 'fec_candidate_id', NULLIF(btrim(fec.value), '')
        FROM jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(v_external_ids -> 'fec') = 'array'
                THEN v_external_ids -> 'fec' ELSE '[]'::jsonb END
        ) AS fec(value)
        WHERE NULLIF(btrim(fec.value), '') IS NOT NULL
        UNION
        SELECT 'fec', 'fec_candidate_id', NULLIF(btrim(v_external_ids ->> 'fec'), '')
        WHERE jsonb_typeof(v_external_ids -> 'fec') IN ('string', 'number')
          AND NULLIF(btrim(v_external_ids ->> 'fec'), '') IS NOT NULL
    ),
    trusted_keys AS (
        SELECT DISTINCT
            btrim(item.value ->> 'source_system_key') AS source_system_key,
            btrim(item.value ->> 'external_id_type') AS external_id_type,
            btrim(item.value ->> 'external_id') AS external_id
        FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
    ),
    missing AS (
        SELECT * FROM profile_keys
        EXCEPT
        SELECT * FROM trusted_keys
    )
    SELECT jsonb_agg(to_jsonb(missing)) INTO v_missing_keys FROM missing;

    IF v_missing_keys IS NOT NULL THEN
        RAISE EXCEPTION 'identity-bearing profile keys were not declared trusted: %', v_missing_keys
            USING ERRCODE = '22023';
    END IF;

    -- Serialize both the source record and every trusted external identity key.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('source-record:' || v_source_key || ':' || v_record_key, 0)
    );
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'identity:' || btrim(item.value ->> 'source_system_key') || ':' ||
            btrim(item.value ->> 'external_id_type') || ':' ||
            btrim(item.value ->> 'external_id'),
            0
        )
    )
    FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
    ORDER BY
        btrim(item.value ->> 'source_system_key'),
        btrim(item.value ->> 'external_id_type'),
        btrim(item.value ->> 'external_id');

    SELECT sr.id, sr.person_id, sr.legacy_politician_id
    INTO v_source_record_id, v_existing_source_person_id, v_existing_legacy_id
    FROM public.source_records AS sr
    WHERE sr.source_system_key = v_source_key
      AND sr.source_record_key = v_record_key
    FOR UPDATE;

    IF COALESCE(jsonb_array_length(COALESCE(p_trusted_external_ids, '[]'::jsonb)), 0) = 0
       AND v_existing_source_person_id IS NULL THEN
        RAISE EXCEPTION 'an initial source profile requires at least one trusted external identity key'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        WITH trusted_keys AS (
            SELECT DISTINCT
                btrim(item.value ->> 'source_system_key') AS source_system_key,
                btrim(item.value ->> 'external_id_type') AS external_id_type,
                btrim(item.value ->> 'external_id') AS external_id
            FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
        )
        SELECT 1
        FROM trusted_keys AS key
        JOIN public.person_external_ids AS pei
          ON pei.source_system_key = key.source_system_key
         AND pei.external_id_type = key.external_id_type
         AND pei.external_id = key.external_id
        JOIN public.people AS owner ON owner.id = pei.person_id
        LEFT JOIN public.people AS survivor ON survivor.id = owner.merged_into_person_id
        WHERE NOT pei.is_trusted
           OR owner.status = 'inactive'
           OR (owner.status = 'merged' AND (
               survivor.id IS NULL OR survivor.status <> 'active' OR survivor.merged_into_person_id IS NOT NULL
           ))
    ) THEN
        RAISE EXCEPTION 'a trusted identity key is owned by an inactive or invalid merged person'
            USING ERRCODE = '23505';
    END IF;

    WITH trusted_keys AS (
        SELECT DISTINCT
            btrim(item.value ->> 'source_system_key') AS source_system_key,
            btrim(item.value ->> 'external_id_type') AS external_id_type,
            btrim(item.value ->> 'external_id') AS external_id
        FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
    ),
    matched AS (
        SELECT DISTINCT
            CASE WHEN pe.status = 'merged' THEN pe.merged_into_person_id ELSE pe.id END AS person_id
        FROM trusted_keys AS key
        JOIN public.person_external_ids AS pei
          ON pei.source_system_key = key.source_system_key
         AND pei.external_id_type = key.external_id_type
         AND pei.external_id = key.external_id
         AND pei.is_trusted
        JOIN public.people AS pe ON pe.id = pei.person_id
        WHERE pe.status IN ('active', 'merged')
    )
    SELECT array_agg(person_id ORDER BY person_id) INTO v_matching_person_ids FROM matched;

    IF COALESCE(array_length(v_matching_person_ids, 1), 0) > 1 THEN
        RAISE EXCEPTION 'trusted identity keys match multiple canonical people: %', v_matching_person_ids
            USING ERRCODE = '23505';
    END IF;

    v_target_person_id := v_matching_person_ids[1];

    IF v_existing_source_person_id IS NOT NULL THEN
        SELECT CASE WHEN pe.status = 'merged' THEN pe.merged_into_person_id ELSE pe.id END
        INTO v_existing_source_person_id
        FROM public.people AS pe
        WHERE pe.id = v_existing_source_person_id
          AND pe.status IN ('active', 'merged');

        IF v_existing_source_person_id IS NULL THEN
            RAISE EXCEPTION 'existing source record points to an inactive or missing person'
                USING ERRCODE = '23503';
        END IF;

        IF v_target_person_id IS NOT NULL AND v_target_person_id <> v_existing_source_person_id THEN
            RAISE EXCEPTION 'source record person conflicts with trusted identity keys'
                USING ERRCODE = '23505';
        END IF;
        v_target_person_id := v_existing_source_person_id;
        v_resolution_action := 'updated_source_record';
    ELSIF v_target_person_id IS NOT NULL THEN
        v_resolution_action := 'matched_existing_person';
    ELSE
        v_resolution_action := 'created_person';
    END IF;

    v_legacy_id := v_existing_legacy_id;

    IF v_legacy_id IS NULL AND v_bioguide_id IS NOT NULL THEN
        SELECT p.id INTO v_legacy_id
        FROM public.politicians AS p
        WHERE p.bioguide_id = v_bioguide_id
        FOR UPDATE;
    END IF;

    -- Adopt a pre-0022 compatibility row only when both its deterministic key and role
    -- snapshot match this source packet. Matching identity alone is insufficient because
    -- one canonical person may legitimately have multiple source/office rows.
    IF v_legacy_id IS NULL THEN
        WITH trusted_keys AS (
            SELECT DISTINCT
                btrim(item.value ->> 'source_system_key') AS source_system_key,
                btrim(item.value ->> 'external_id_type') AS external_id_type,
                btrim(item.value ->> 'external_id') AS external_id
            FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
        ),
        candidates AS (
            SELECT DISTINCT p.id
            FROM public.politicians AS p
            JOIN trusted_keys AS key ON (
                (key.source_system_key = 'bioguide' AND (
                    p.bioguide_id = key.external_id
                    OR p.external_ids ->> 'bioguide' = key.external_id
                ))
                OR p.external_ids ->> key.source_system_key = key.external_id
            )
            WHERE public.normalize_identity_name(p.full_name) = public.normalize_identity_name(v_full_name)
              AND lower(btrim(COALESCE(p.current_office, ''))) =
                  lower(btrim(COALESCE(p_profile ->> 'current_office', '')))
        )
        SELECT count(*), min(id::text)::uuid
        INTO v_candidate_count, v_legacy_id
        FROM candidates;

        IF v_candidate_count > 1 THEN
            RAISE EXCEPTION 'source profile matches multiple pre-0022 legacy role rows'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    IF v_legacy_id IS NULL THEN
        SELECT count(*), min(p.id::text)::uuid
        INTO v_candidate_count, v_legacy_id
        FROM public.politicians AS p
        WHERE p.external_ids ->> v_source_key = v_record_key;
        IF v_candidate_count > 1 THEN
            RAISE EXCEPTION 'source record matches multiple legacy politician rows'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    IF v_legacy_id IS NOT NULL THEN
        SELECT l.person_id INTO v_redirect_person_id
        FROM public.legacy_profile_redirects AS l
        WHERE l.legacy_politician_id = v_legacy_id;

        IF v_redirect_person_id IS NOT NULL THEN
            SELECT CASE WHEN pe.status = 'merged' THEN pe.merged_into_person_id ELSE pe.id END
            INTO v_resolved_redirect_person_id
            FROM public.people AS pe
            LEFT JOIN public.people AS survivor ON survivor.id = pe.merged_into_person_id
            WHERE pe.id = v_redirect_person_id
              AND (
                  pe.status = 'active'
                  OR (pe.status = 'merged' AND survivor.status = 'active')
              );

            IF v_resolved_redirect_person_id IS NULL THEN
                RAISE EXCEPTION 'legacy profile redirect points to an inactive or invalid person'
                    USING ERRCODE = '23503';
            END IF;

            IF v_target_person_id IS NOT NULL AND v_resolved_redirect_person_id <> v_target_person_id THEN
                RAISE EXCEPTION 'legacy profile redirect conflicts with pre-resolved source identity'
                    USING ERRCODE = '23505';
            END IF;
            v_target_person_id := COALESCE(v_target_person_id, v_resolved_redirect_person_id);
        END IF;
    END IF;

    IF v_legacy_id IS NULL THEN
        INSERT INTO public.politicians (
            full_name, current_office, party, state, district,
            government_level, government_branch, office_type, jurisdiction,
            bioguide_id, external_ids, aliases, last_updated
        ) VALUES (
            v_full_name,
            NULLIF(btrim(p_profile ->> 'current_office'), ''),
            NULLIF(btrim(p_profile ->> 'party'), ''),
            NULLIF(btrim(p_profile ->> 'state'), ''),
            NULLIF(btrim(p_profile ->> 'district'), ''),
            NULLIF(btrim(p_profile ->> 'government_level'), ''),
            NULLIF(btrim(p_profile ->> 'government_branch'), ''),
            NULLIF(btrim(p_profile ->> 'office_type'), ''),
            NULLIF(btrim(p_profile ->> 'jurisdiction'), ''),
            v_bioguide_id,
            v_external_ids,
            v_aliases,
            now()
        )
        RETURNING id INTO v_legacy_id;
    ELSE
        UPDATE public.politicians AS p
        SET
            full_name = v_full_name,
            current_office = CASE WHEN p_profile ? 'current_office'
                THEN NULLIF(btrim(p_profile ->> 'current_office'), '') ELSE p.current_office END,
            party = CASE WHEN p_profile ? 'party'
                THEN NULLIF(btrim(p_profile ->> 'party'), '') ELSE p.party END,
            state = CASE WHEN p_profile ? 'state'
                THEN NULLIF(btrim(p_profile ->> 'state'), '') ELSE p.state END,
            district = CASE WHEN p_profile ? 'district'
                THEN NULLIF(btrim(p_profile ->> 'district'), '') ELSE p.district END,
            government_level = CASE WHEN p_profile ? 'government_level'
                THEN NULLIF(btrim(p_profile ->> 'government_level'), '') ELSE p.government_level END,
            government_branch = CASE WHEN p_profile ? 'government_branch'
                THEN NULLIF(btrim(p_profile ->> 'government_branch'), '') ELSE p.government_branch END,
            office_type = CASE WHEN p_profile ? 'office_type'
                THEN NULLIF(btrim(p_profile ->> 'office_type'), '') ELSE p.office_type END,
            jurisdiction = CASE WHEN p_profile ? 'jurisdiction'
                THEN NULLIF(btrim(p_profile ->> 'jurisdiction'), '') ELSE p.jurisdiction END,
            bioguide_id = COALESCE(v_bioguide_id, p.bioguide_id),
            external_ids = p.external_ids || v_external_ids,
            aliases = CASE WHEN p_profile ? 'aliases' THEN v_aliases ELSE p.aliases END,
            last_updated = now()
        WHERE p.id = v_legacy_id;
    END IF;

    IF v_target_person_id IS NOT NULL THEN
        SELECT COALESCE(l.canonical_politician_id, l.legacy_politician_id)
        INTO v_canonical_legacy_id
        FROM public.legacy_profile_redirects AS l
        WHERE l.person_id = v_target_person_id
        ORDER BY (l.canonical_politician_id IS NOT NULL) DESC, l.created_at, l.legacy_politician_id
        LIMIT 1;

        INSERT INTO public.legacy_profile_redirects (
            legacy_politician_id, person_id, canonical_politician_id, resolution_method, confidence
        ) VALUES (
            v_legacy_id,
            v_target_person_id,
            COALESCE(v_canonical_legacy_id, v_legacy_id),
            'source_record_deterministic',
            1.000
        )
        ON CONFLICT (legacy_politician_id) DO NOTHING;

        INSERT INTO public.person_external_ids (
            person_id, source_system_key, external_id_type, external_id,
            is_trusted, source_legacy_politician_id
        )
        SELECT DISTINCT
            v_target_person_id,
            btrim(item.value ->> 'source_system_key'),
            btrim(item.value ->> 'external_id_type'),
            btrim(item.value ->> 'external_id'),
            true,
            v_legacy_id
        FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
        ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            is_trusted = true,
            source_legacy_politician_id = COALESCE(
                public.person_external_ids.source_legacy_politician_id,
                EXCLUDED.source_legacy_politician_id
            );
    END IF;

    IF v_target_person_id IS NOT NULL THEN
        -- The source packet was pre-resolved. Bind the compatibility identifiers and name
        -- directly instead of asking the legacy sync function to infer identity again.
        INSERT INTO public.person_external_ids (
            person_id, source_system_key, external_id_type, external_id,
            is_trusted, source_legacy_politician_id
        ) VALUES (
            v_target_person_id,
            'avanguardia-legacy-profile',
            'politicians.id',
            v_legacy_id::text,
            true,
            v_legacy_id
        )
        ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            source_legacy_politician_id = EXCLUDED.source_legacy_politician_id;

        INSERT INTO public.person_names (
            person_id, source_system_key, legacy_politician_id,
            name_text, normalized_name, name_type, is_primary
        ) VALUES (
            v_target_person_id,
            'avanguardia-legacy-profile',
            v_legacy_id,
            v_full_name,
            public.normalize_identity_name(v_full_name),
            'profile_name',
            false
        )
        ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO NOTHING;

        v_synced_person_id := v_target_person_id;
    ELSE
        SELECT synced.person_id INTO v_synced_person_id
        FROM public.sync_legacy_profile_identity(v_legacy_id) AS synced
        LIMIT 1;
    END IF;

    IF v_synced_person_id IS NULL THEN
        RAISE EXCEPTION 'canonical identity sync returned no person' USING ERRCODE = '23503';
    END IF;

    IF v_target_person_id IS NOT NULL AND v_synced_person_id <> v_target_person_id THEN
        RAISE EXCEPTION 'canonical identity sync disagreed with the pre-resolved person'
            USING ERRCODE = '23505';
    END IF;
    v_target_person_id := v_synced_person_id;

    INSERT INTO public.person_external_ids (
        person_id, source_system_key, external_id_type, external_id,
        is_trusted, source_legacy_politician_id
    )
    SELECT DISTINCT
        v_target_person_id,
        btrim(item.value ->> 'source_system_key'),
        btrim(item.value ->> 'external_id_type'),
        btrim(item.value ->> 'external_id'),
        true,
        v_legacy_id
    FROM jsonb_array_elements(COALESCE(p_trusted_external_ids, '[]'::jsonb)) AS item(value)
    ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
        person_id = EXCLUDED.person_id,
        is_trusted = true,
        source_legacy_politician_id = COALESCE(
            public.person_external_ids.source_legacy_politician_id,
            EXCLUDED.source_legacy_politician_id
        );

    INSERT INTO public.source_records (
        source_system_key, source_record_key, record_type, person_id,
        legacy_politician_id, source_catalog_slug, source_endpoint_slug,
        source_url, raw_payload_ref, payload_hash, verified_lane, record_status,
        source_updated_at, last_seen_at, metadata
    ) VALUES (
        v_source_key, v_record_key, 'person_profile', v_target_person_id,
        v_legacy_id, p_source_catalog_slug, p_source_endpoint_slug,
        NULLIF(btrim(p_source_url), ''), NULLIF(btrim(p_raw_payload_ref), ''),
        NULLIF(btrim(p_payload_hash), ''), p_verified_lane, 'active',
        p_source_updated_at, now(),
        jsonb_build_object('last_profile_name', v_full_name)
    )
    ON CONFLICT (source_system_key, source_record_key) DO UPDATE SET
        person_id = EXCLUDED.person_id,
        legacy_politician_id = EXCLUDED.legacy_politician_id,
        source_catalog_slug = COALESCE(EXCLUDED.source_catalog_slug, public.source_records.source_catalog_slug),
        source_endpoint_slug = COALESCE(EXCLUDED.source_endpoint_slug, public.source_records.source_endpoint_slug),
        source_url = COALESCE(EXCLUDED.source_url, public.source_records.source_url),
        raw_payload_ref = COALESCE(EXCLUDED.raw_payload_ref, public.source_records.raw_payload_ref),
        payload_hash = COALESCE(EXCLUDED.payload_hash, public.source_records.payload_hash),
        verified_lane = EXCLUDED.verified_lane,
        record_status = 'active',
        source_updated_at = COALESCE(EXCLUDED.source_updated_at, public.source_records.source_updated_at),
        retired_at = NULL,
        last_seen_at = now(),
        metadata = public.source_records.metadata || EXCLUDED.metadata
    RETURNING id INTO v_source_record_id;

    IF jsonb_typeof(p_office_term) = 'object'
       AND NULLIF(btrim(COALESCE(p_office_term ->> 'office_title', p_profile ->> 'current_office')), '') IS NOT NULL THEN
        IF COALESCE(NULLIF(btrim(p_office_term ->> 'term_status'), ''), 'current') = 'current' THEN
            UPDATE public.person_office_terms AS prior
            SET term_status = 'historical'
            WHERE prior.source_record_id = v_source_record_id
              AND prior.term_status = 'current'
              AND prior.source_term_key <> COALESCE(
                  NULLIF(btrim(p_office_term ->> 'source_term_key'), ''),
                  'current-office'
              );
        END IF;

        INSERT INTO public.person_office_terms (
            person_id, source_record_id, source_term_key, legacy_politician_id,
            office_title, role_type, organization_name, government_level,
            government_branch, office_type, jurisdiction, state, district,
            term_start, term_end, term_status, metadata
        ) VALUES (
            v_target_person_id,
            v_source_record_id,
            COALESCE(NULLIF(btrim(p_office_term ->> 'source_term_key'), ''), 'current-office'),
            v_legacy_id,
            NULLIF(btrim(COALESCE(p_office_term ->> 'office_title', p_profile ->> 'current_office')), ''),
            COALESCE(NULLIF(btrim(p_office_term ->> 'role_type'), ''), 'office'),
            NULLIF(btrim(p_office_term ->> 'organization_name'), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'government_level', p_profile ->> 'government_level')), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'government_branch', p_profile ->> 'government_branch')), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'office_type', p_profile ->> 'office_type')), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'jurisdiction', p_profile ->> 'jurisdiction')), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'state', p_profile ->> 'state')), ''),
            NULLIF(btrim(COALESCE(p_office_term ->> 'district', p_profile ->> 'district')), ''),
            NULLIF(btrim(p_office_term ->> 'term_start'), '')::date,
            NULLIF(btrim(p_office_term ->> 'term_end'), '')::date,
            COALESCE(NULLIF(btrim(p_office_term ->> 'term_status'), ''), 'current'),
            CASE WHEN jsonb_typeof(p_office_term -> 'metadata') = 'object'
                THEN p_office_term -> 'metadata' ELSE '{}'::jsonb END
        )
        ON CONFLICT (source_record_id, source_term_key) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            legacy_politician_id = EXCLUDED.legacy_politician_id,
            office_title = EXCLUDED.office_title,
            role_type = EXCLUDED.role_type,
            organization_name = EXCLUDED.organization_name,
            government_level = EXCLUDED.government_level,
            government_branch = EXCLUDED.government_branch,
            office_type = EXCLUDED.office_type,
            jurisdiction = EXCLUDED.jurisdiction,
            state = EXCLUDED.state,
            district = EXCLUDED.district,
            term_start = EXCLUDED.term_start,
            term_end = EXCLUDED.term_end,
            term_status = EXCLUDED.term_status,
            metadata = public.person_office_terms.metadata || EXCLUDED.metadata
        RETURNING id INTO v_office_term_id;
    END IF;

    RETURN QUERY
    SELECT v_target_person_id, v_legacy_id, v_source_record_id, v_office_term_id, v_resolution_action;
END;
$$;

-- Retire the source snapshot and every still-current term as one database operation.
-- The all-zero UUID is reserved for the scraper's non-mutating schema preflight.
CREATE OR REPLACE FUNCTION public.retire_source_profile_record(
    p_source_record_id uuid,
    p_retired_at timestamptz DEFAULT now(),
    p_term_end date DEFAULT current_date
)
RETURNS TABLE (
    source_record_id uuid,
    person_id uuid,
    retired_office_term_count integer,
    record_status text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_person_id uuid;
    v_existing_status text;
    v_retired_term_count integer := 0;
    v_retired_at timestamptz := COALESCE(p_retired_at, now());
    v_term_end date := COALESCE(p_term_end, p_retired_at::date, current_date);
BEGIN
    IF p_source_record_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RETURN QUERY
        SELECT p_source_record_id, NULL::uuid, 0, 'preflight_ok'::text;
        RETURN;
    END IF;

    IF p_source_record_id IS NULL THEN
        RAISE EXCEPTION 'source_record_id is required' USING ERRCODE = '22023';
    END IF;

    SELECT sr.person_id, sr.record_status
    INTO v_person_id, v_existing_status
    FROM public.source_records AS sr
    WHERE sr.id = p_source_record_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'source record % does not exist', p_source_record_id
            USING ERRCODE = '23503';
    END IF;

    IF v_existing_status = 'deleted' THEN
        RAISE EXCEPTION 'deleted source record % cannot be retired', p_source_record_id
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.person_office_terms AS term
    SET
        term_status = 'historical',
        term_end = CASE
            WHEN term.term_end IS NOT NULL AND term.term_end <= v_term_end
                THEN term.term_end
            ELSE GREATEST(COALESCE(term.term_start, v_term_end), v_term_end)
        END,
        metadata = term.metadata || jsonb_build_object(
            'retired_by', 'retire_source_profile_record',
            'retired_at', v_retired_at
        )
    WHERE term.source_record_id = p_source_record_id
      AND term.term_status = 'current';

    GET DIAGNOSTICS v_retired_term_count = ROW_COUNT;

    UPDATE public.source_records AS sr
    SET
        record_status = 'retired',
        retired_at = COALESCE(sr.retired_at, v_retired_at),
        metadata = sr.metadata || jsonb_build_object(
            'retirement_rpc_at', v_retired_at
        )
    WHERE sr.id = p_source_record_id;

    RETURN QUERY
    SELECT p_source_record_id, v_person_id, v_retired_term_count, 'retired'::text;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.get_legacy_profile_identity_keys(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.upsert_source_profile_identity(
    text, text, jsonb, jsonb, text, text, text, text, jsonb, text, text, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_source_profile_identity(
    text, text, jsonb, jsonb, text, text, text, text, jsonb, text, text, timestamptz
) TO service_role;
REVOKE EXECUTE ON FUNCTION public.retire_source_profile_record(uuid, timestamptz, date)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.retire_source_profile_record(uuid, timestamptz, date)
    TO service_role;

CREATE OR REPLACE VIEW public.canonical_person_current_office_terms AS
SELECT DISTINCT ON (term.person_id)
    term.person_id,
    term.id AS office_term_id,
    term.source_record_id,
    term.legacy_politician_id,
    term.office_title,
    term.role_type,
    term.organization_name,
    term.government_level,
    term.government_branch,
    term.office_type,
    term.jurisdiction,
    term.state,
    term.district,
    term.term_start,
    term.term_end,
    source.verified_lane,
    source.last_seen_at,
    legacy.party
FROM public.person_office_terms AS term
JOIN public.source_records AS source ON source.id = term.source_record_id
LEFT JOIN public.politicians AS legacy ON legacy.id = term.legacy_politician_id
WHERE term.term_status = 'current'
  AND source.record_status = 'active'
  AND source.verified_lane IN ('verified', 'mixed')
  AND (term.term_start IS NULL OR term.term_start <= current_date)
  AND (term.term_end IS NULL OR term.term_end >= current_date)
ORDER BY
    term.person_id,
    CASE source.verified_lane
        WHEN 'verified' THEN 0
        WHEN 'mixed' THEN 1
        WHEN 'unknown' THEN 2
        ELSE 3
    END,
    term.term_start DESC NULLS LAST,
    source.last_seen_at DESC,
    term.id;

CREATE OR REPLACE FUNCTION public.get_canonical_politician_header(p_id uuid)
RETURNS TABLE (
    id uuid,
    full_name text,
    current_office text,
    party text,
    state text,
    district text,
    last_updated timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT * FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    ranked_profiles AS (
        SELECT
            l.person_id,
            p.*,
            row_number() OVER (
                PARTITION BY l.person_id
                ORDER BY
                    l.is_canonical DESC,
                    CASE WHEN NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL THEN 1 ELSE 0 END DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM legacy AS l
        JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        rp.person_id AS id,
        COALESCE(pe.primary_name, rp.full_name) AS full_name,
        COALESCE(role.office_title, rp.current_office) AS current_office,
        CASE WHEN role.person_id IS NOT NULL THEN role.party ELSE rp.party END AS party,
        CASE WHEN role.person_id IS NOT NULL THEN role.state ELSE rp.state END AS state,
        CASE WHEN role.person_id IS NOT NULL THEN role.district ELSE rp.district END AS district,
        GREATEST(rp.last_updated, role.last_seen_at) AS last_updated
    FROM ranked_profiles AS rp
    LEFT JOIN public.people AS pe ON pe.id = rp.person_id AND pe.status = 'active'
    LEFT JOIN public.canonical_person_current_office_terms AS role ON role.person_id = rp.person_id
    WHERE rp.profile_rank = 1
    LIMIT 1;
$$;

-- Final summary definition preserves the initials/partial-name ranking introduced by
-- migration 0013 while adding the active canonical role as another searchable surface.
CREATE OR REPLACE FUNCTION public.get_canonical_politician_summaries(
    search_query text DEFAULT NULL,
    result_limit integer DEFAULT 1000,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    full_name text,
    current_office text,
    party text,
    state text,
    district text,
    government_level text,
    government_branch text,
    office_type text,
    jurisdiction text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH raw_params AS (
        SELECT
            NULLIF(btrim(search_query), '') AS q,
            NULLIF(
                btrim(regexp_replace(
                    lower(btrim(coalesce(search_query, ''))),
                    '[^a-z0-9]+', ' ', 'g'
                )),
                ''
            ) AS q_norm,
            NULLIF(
                regexp_replace(
                    lower(btrim(coalesce(search_query, ''))),
                    '[^a-z0-9]+', '', 'g'
                ),
                ''
            ) AS q_compact
    ),
    params AS (
        SELECT
            q,
            q_norm,
            q_compact,
            CASE WHEN q IS NULL THEN NULL::tsquery
                ELSE websearch_to_tsquery('english', q) END AS q_ts
        FROM raw_params
    ),
    mapped_profiles AS (
        SELECT
            l.person_id,
            l.legacy_politician_id,
            l.legacy_politician_id = l.canonical_politician_id AS is_canonical
        FROM public.legacy_profile_redirects AS l
        JOIN public.people AS pe ON pe.id = l.person_id
        WHERE pe.status = 'active'

        UNION ALL

        SELECT p.id, p.id, true
        FROM public.politicians AS p
        WHERE NOT EXISTS (
            SELECT 1 FROM public.legacy_profile_redirects AS l
            WHERE l.legacy_politician_id = p.id
        )
    ),
    search_candidates AS (
        SELECT
            mp.person_id,
            p.search_vector,
            to_tsvector('english', coalesce(pe.primary_name, '')) AS primary_name_search_vector,
            lower(coalesce(pe.primary_name, p.full_name, '')) AS display_lower,
            lower(coalesce(p.full_name, '')) AS legacy_lower,
            lower(coalesce(role.office_title, '')) AS role_lower,
            btrim(regexp_replace(
                btrim(lower(coalesce(pe.primary_name, p.full_name, ''))),
                '[^a-z0-9]+', ' ', 'g'
            )) AS display_norm,
            btrim(regexp_replace(
                btrim(lower(coalesce(p.full_name, ''))),
                '[^a-z0-9]+', ' ', 'g'
            )) AS legacy_norm,
            btrim(regexp_replace(
                btrim(lower(coalesce(role.office_title, ''))),
                '[^a-z0-9]+', ' ', 'g'
            )) AS role_norm,
            regexp_replace(
                lower(coalesce(pe.primary_name, p.full_name, '')),
                '[^a-z0-9]+', '', 'g'
            ) AS display_compact,
            regexp_replace(
                lower(coalesce(p.full_name, '')),
                '[^a-z0-9]+', '', 'g'
            ) AS legacy_compact,
            regexp_replace(
                lower(coalesce(role.office_title, '')),
                '[^a-z0-9]+', '', 'g'
            ) AS role_compact
        FROM mapped_profiles AS mp
        JOIN public.politicians AS p ON p.id = mp.legacy_politician_id
        LEFT JOIN public.people AS pe ON pe.id = mp.person_id
        LEFT JOIN public.canonical_person_current_office_terms AS role
          ON role.person_id = mp.person_id
    ),
    matching_people AS (
        SELECT
            sc.person_id,
            bool_or(
                params.q IS NULL
                OR COALESCE(sc.search_vector @@ params.q_ts, false)
                OR COALESCE(sc.primary_name_search_vector @@ params.q_ts, false)
                OR (
                    params.q IS NOT NULL
                    AND (
                        sc.display_lower LIKE lower(params.q) || '%'
                        OR sc.legacy_lower LIKE lower(params.q) || '%'
                        OR sc.role_lower LIKE lower(params.q) || '%'
                    )
                )
                OR (
                    params.q_norm IS NOT NULL
                    AND (
                        sc.display_norm LIKE params.q_norm || '%'
                        OR sc.legacy_norm LIKE params.q_norm || '%'
                        OR sc.role_norm LIKE params.q_norm || '%'
                        OR sc.display_norm LIKE '% ' || params.q_norm || '%'
                        OR sc.legacy_norm LIKE '% ' || params.q_norm || '%'
                        OR sc.role_norm LIKE '% ' || params.q_norm || '%'
                    )
                )
                OR (
                    params.q_compact IS NOT NULL
                    AND (
                        sc.display_compact LIKE params.q_compact || '%'
                        OR sc.legacy_compact LIKE params.q_compact || '%'
                        OR sc.role_compact LIKE params.q_compact || '%'
                    )
                )
            ) AS matches_search,
            min(
                CASE
                    WHEN params.q IS NULL THEN 3
                    WHEN params.q_norm IS NOT NULL AND (
                        sc.display_norm = params.q_norm
                        OR sc.legacy_norm = params.q_norm
                        OR sc.role_norm = params.q_norm
                    ) THEN 0
                    WHEN params.q_compact IS NOT NULL AND (
                        sc.display_compact = params.q_compact
                        OR sc.legacy_compact = params.q_compact
                        OR sc.role_compact = params.q_compact
                    ) THEN 0
                    WHEN params.q IS NOT NULL AND (
                        sc.display_lower LIKE lower(params.q) || '%'
                        OR sc.legacy_lower LIKE lower(params.q) || '%'
                        OR sc.role_lower LIKE lower(params.q) || '%'
                    ) THEN 1
                    WHEN params.q_norm IS NOT NULL AND (
                        sc.display_norm LIKE params.q_norm || '%'
                        OR sc.legacy_norm LIKE params.q_norm || '%'
                        OR sc.role_norm LIKE params.q_norm || '%'
                    ) THEN 1
                    WHEN params.q_compact IS NOT NULL AND (
                        sc.display_compact LIKE params.q_compact || '%'
                        OR sc.legacy_compact LIKE params.q_compact || '%'
                        OR sc.role_compact LIKE params.q_compact || '%'
                    ) THEN 1
                    WHEN params.q_norm IS NOT NULL AND (
                        sc.display_norm LIKE '% ' || params.q_norm || '%'
                        OR sc.legacy_norm LIKE '% ' || params.q_norm || '%'
                        OR sc.role_norm LIKE '% ' || params.q_norm || '%'
                    ) THEN 2
                    WHEN COALESCE(sc.search_vector @@ params.q_ts, false)
                      OR COALESCE(sc.primary_name_search_vector @@ params.q_ts, false)
                        THEN 3
                    ELSE 4
                END
            ) AS search_rank
        FROM search_candidates AS sc
        CROSS JOIN params
        GROUP BY sc.person_id
    ),
    ranked_profiles AS (
        SELECT
            mp.person_id,
            p.*,
            row_number() OVER (
                PARTITION BY mp.person_id
                ORDER BY
                    mp.is_canonical DESC,
                    CASE WHEN NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL THEN 1 ELSE 0 END DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM mapped_profiles AS mp
        JOIN public.politicians AS p ON p.id = mp.legacy_politician_id
    )
    SELECT
        rp.person_id AS id,
        COALESCE(pe.primary_name, rp.full_name) AS full_name,
        COALESCE(role.office_title, rp.current_office) AS current_office,
        CASE WHEN role.person_id IS NOT NULL THEN role.party ELSE rp.party END AS party,
        CASE WHEN role.person_id IS NOT NULL THEN role.state ELSE rp.state END AS state,
        CASE WHEN role.person_id IS NOT NULL THEN role.district ELSE rp.district END AS district,
        CASE WHEN role.person_id IS NOT NULL THEN role.government_level ELSE rp.government_level END AS government_level,
        CASE WHEN role.person_id IS NOT NULL THEN role.government_branch ELSE rp.government_branch END AS government_branch,
        CASE WHEN role.person_id IS NOT NULL THEN role.office_type ELSE rp.office_type END AS office_type,
        CASE WHEN role.person_id IS NOT NULL THEN role.jurisdiction ELSE rp.jurisdiction END AS jurisdiction
    FROM matching_people AS matched
    JOIN ranked_profiles AS rp ON rp.person_id = matched.person_id AND rp.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = rp.person_id AND pe.status = 'active'
    LEFT JOIN public.canonical_person_current_office_terms AS role ON role.person_id = rp.person_id
    WHERE matched.matches_search
    ORDER BY matched.search_rank, COALESCE(pe.primary_name, rp.full_name), rp.person_id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 1000), 0), 1000)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

REVOKE ALL ON TABLE public.canonical_person_current_office_terms
    FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.canonical_person_current_office_terms TO service_role;

REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) TO anon, authenticated;


WITH corrected AS (
    UPDATE public.source_catalog_endpoints AS e
    SET
        status = 'candidate',
        notes = CASE
            WHEN e.notes ILIKE '%no extractor%' THEN e.notes
            ELSE concat_ws(' ', e.notes, 'No Federal Judicial Center extractor exists yet.')
        END
    WHERE e.source_slug = 'fjc'
      AND e.endpoint_slug = 'judges-directory'
      AND e.status = 'approved'
      AND NOT EXISTS (
          SELECT 1
          FROM public.source_catalog_review_events AS review
          WHERE review.source_slug = e.source_slug
            AND review.endpoint_slug = e.endpoint_slug
      )
    RETURNING e.source_slug, e.endpoint_slug
)
INSERT INTO public.source_catalog_review_events (
    source_slug,
    endpoint_slug,
    previous_status,
    new_status,
    reviewer,
    reason,
    evidence
)
SELECT
    corrected.source_slug,
    corrected.endpoint_slug,
    'approved',
    'candidate',
    'migration-0022',
    'Corrected endpoint status: the FJC directory is not yet wired to an extractor.',
    jsonb_build_object('migration', '0022_project_stabilization')
FROM corrected;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.identity_validation_invalid_merge_state) THEN
        RAISE EXCEPTION '0022 cannot finalize: invalid merge-state rows remain';
    END IF;
    IF EXISTS (SELECT 1 FROM public.identity_validation_redirect_person_status) THEN
        RAISE EXCEPTION '0022 cannot finalize: redirects still target non-active people';
    END IF;
    IF EXISTS (SELECT 1 FROM public.identity_validation_spoke_person_mismatch) THEN
        RAISE EXCEPTION '0022 cannot finalize: canonical spoke person_id mismatches remain';
    END IF;
    IF EXISTS (SELECT 1 FROM public.source_record_validation_identity_mismatch) THEN
        RAISE EXCEPTION '0022 cannot finalize: source-record identity mismatches remain';
    END IF;
    IF EXISTS (SELECT 1 FROM public.source_record_validation_lifecycle_mismatch) THEN
        RAISE EXCEPTION '0022 cannot finalize: retired source records still have current office terms';
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

COMMIT;
