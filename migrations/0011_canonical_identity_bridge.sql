-- 0011_canonical_identity_bridge.sql
--
-- Phase 1 of docs/canonical_data_and_analytics_plan.md.
--
-- Adds an explicit canonical person bridge while preserving legacy politicians.id
-- profile UUIDs and all existing spoke tables. This migration is idempotent and safe
-- to re-run manually in the Supabase SQL editor.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.normalize_identity_name(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = ''
AS $$
    SELECT NULLIF(regexp_replace(lower(btrim(coalesce(value, ''))), '\s+', ' ', 'g'), '');
$$;

CREATE TABLE IF NOT EXISTS public.source_systems (
    key text PRIMARY KEY,
    display_name text NOT NULL,
    source_kind text NOT NULL DEFAULT 'reference',
    trust_level text NOT NULL DEFAULT 'unverified',
    verified boolean NOT NULL DEFAULT false,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.people (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    primary_name text NOT NULL,
    display_name text,
    status text NOT NULL DEFAULT 'active',
    merged_into_person_id uuid REFERENCES public.people(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'people_status_check'
          AND conrelid = 'public.people'::regclass
    ) THEN
        ALTER TABLE public.people
            ADD CONSTRAINT people_status_check
            CHECK (status IN ('active', 'merged', 'inactive'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.person_external_ids (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE CASCADE,
    source_system_key text NOT NULL REFERENCES public.source_systems(key) ON DELETE RESTRICT,
    external_id_type text NOT NULL,
    external_id text NOT NULL,
    is_trusted boolean NOT NULL DEFAULT true,
    source_legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.person_names (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE CASCADE,
    source_system_key text NOT NULL REFERENCES public.source_systems(key) ON DELETE RESTRICT,
    legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE SET NULL,
    name_text text NOT NULL,
    normalized_name text NOT NULL,
    name_type text NOT NULL DEFAULT 'profile_name',
    is_primary boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.legacy_profile_redirects (
    legacy_politician_id uuid PRIMARY KEY REFERENCES public.politicians(id) ON DELETE CASCADE,
    person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE RESTRICT,
    canonical_politician_id uuid REFERENCES public.politicians(id) ON DELETE SET NULL,
    resolution_method text NOT NULL,
    confidence numeric(4, 3) NOT NULL DEFAULT 1.000,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.identity_resolution_candidates (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_type text NOT NULL,
    source_legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE CASCADE,
    candidate_legacy_politician_id uuid REFERENCES public.politicians(id) ON DELETE CASCADE,
    source_person_id uuid REFERENCES public.people(id) ON DELETE CASCADE,
    candidate_person_id uuid REFERENCES public.people(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending',
    score numeric,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'identity_resolution_candidates_status_check'
          AND conrelid = 'public.identity_resolution_candidates'::regclass
    ) THEN
        ALTER TABLE public.identity_resolution_candidates
            ADD CONSTRAINT identity_resolution_candidates_status_check
            CHECK (status IN ('pending', 'approved', 'rejected', 'blocked'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.person_merge_events (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    survivor_person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE RESTRICT,
    merged_person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE RESTRICT,
    reason text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_people_status ON public.people(status);
CREATE INDEX IF NOT EXISTS idx_people_merged_into ON public.people(merged_into_person_id);
CREATE INDEX IF NOT EXISTS idx_person_external_ids_person ON public.person_external_ids(person_id);
CREATE INDEX IF NOT EXISTS idx_person_external_ids_source ON public.person_external_ids(source_system_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_person_external_ids_unique
    ON public.person_external_ids(source_system_key, external_id_type, external_id);
CREATE INDEX IF NOT EXISTS idx_person_names_person ON public.person_names(person_id);
CREATE INDEX IF NOT EXISTS idx_person_names_normalized ON public.person_names(normalized_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_person_names_unique
    ON public.person_names(person_id, source_system_key, normalized_name, name_type);
CREATE INDEX IF NOT EXISTS idx_legacy_profile_redirects_person
    ON public.legacy_profile_redirects(person_id);
CREATE INDEX IF NOT EXISTS idx_legacy_profile_redirects_canonical
    ON public.legacy_profile_redirects(canonical_politician_id);
CREATE INDEX IF NOT EXISTS idx_identity_resolution_candidates_status
    ON public.identity_resolution_candidates(status, candidate_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_resolution_candidates_pair
    ON public.identity_resolution_candidates(
        candidate_type,
        source_legacy_politician_id,
        candidate_legacy_politician_id
    )
    WHERE source_legacy_politician_id IS NOT NULL
      AND candidate_legacy_politician_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_person_merge_events_survivor
    ON public.person_merge_events(survivor_person_id);
CREATE INDEX IF NOT EXISTS idx_person_merge_events_merged
    ON public.person_merge_events(merged_person_id);

DROP TRIGGER IF EXISTS source_systems_set_updated_at ON public.source_systems;
CREATE TRIGGER source_systems_set_updated_at
    BEFORE UPDATE ON public.source_systems
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS people_set_updated_at ON public.people;
CREATE TRIGGER people_set_updated_at
    BEFORE UPDATE ON public.people
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS person_external_ids_set_updated_at ON public.person_external_ids;
CREATE TRIGGER person_external_ids_set_updated_at
    BEFORE UPDATE ON public.person_external_ids
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS person_names_set_updated_at ON public.person_names;
CREATE TRIGGER person_names_set_updated_at
    BEFORE UPDATE ON public.person_names
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS legacy_profile_redirects_set_updated_at ON public.legacy_profile_redirects;
CREATE TRIGGER legacy_profile_redirects_set_updated_at
    BEFORE UPDATE ON public.legacy_profile_redirects
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS identity_resolution_candidates_set_updated_at
    ON public.identity_resolution_candidates;
CREATE TRIGGER identity_resolution_candidates_set_updated_at
    BEFORE UPDATE ON public.identity_resolution_candidates
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

INSERT INTO public.source_systems (
    key,
    display_name,
    source_kind,
    trust_level,
    verified,
    notes
) VALUES
    (
        'avanguardia-legacy-profile',
        'Avanguardia legacy politician profile',
        'internal',
        'legacy',
        true,
        'Existing politicians.id UUIDs preserved for profile redirects.'
    ),
    (
        'bioguide',
        'Bioguide',
        'government',
        'official',
        true,
        'Official congressional person identifier.'
    ),
    (
        'congress-legislators',
        'unitedstates/congress-legislators',
        'open-data',
        'trusted',
        true,
        'Open-source congressional roster and crosswalk data.'
    ),
    (
        'openstates',
        'OpenStates people',
        'open-data',
        'trusted',
        true,
        'OpenStates ocd-person identifiers for state officials.'
    ),
    (
        'govtrack',
        'GovTrack',
        'open-data',
        'trusted',
        true,
        'GovTrack person identifiers used for federal voting records.'
    ),
    (
        'fec',
        'Federal Election Commission',
        'government',
        'official',
        true,
        'FEC candidate identifiers used for campaign finance joins.'
    ),
    (
        'wikidata',
        'Wikidata',
        'open-data',
        'trusted-crosswalk',
        true,
        'Wikidata QIDs used only when sourced from trusted crosswalks.'
    ),
    (
        'fjc',
        'Federal Judicial Center',
        'government',
        'official',
        true,
        'FJC judge identifiers reserved for federal judicial sources.'
    ),
    (
        'house-clerk',
        'U.S. House Clerk',
        'government',
        'official',
        true,
        'Official House financial disclosure filing index.'
    ),
    (
        'openfec',
        'OpenFEC API',
        'government',
        'official',
        true,
        'Public FEC API used for campaign donor records.'
    ),
    (
        'littlesis',
        'LittleSis',
        'third-party',
        'unverified',
        false,
        'Third-party network and mention source; never a deterministic identity join.'
    ),
    (
        'news-aggregator',
        'News aggregator pipeline',
        'third-party',
        'unverified',
        false,
        'Third-party media mentions gathered by the multi-tier news pipeline.'
    ),
    (
        'currents',
        'Currents API',
        'third-party',
        'unverified',
        false,
        'Free-tier news provider.'
    ),
    (
        'newsdata',
        'NewsData.io',
        'third-party',
        'unverified',
        false,
        'Free-tier news provider.'
    ),
    (
        'thenewsapi',
        'TheNewsAPI',
        'third-party',
        'unverified',
        false,
        'Free-tier news provider.'
    ),
    (
        'gdelt',
        'GDELT',
        'open-data',
        'unverified',
        false,
        'Open-data media fallback source.'
    )
ON CONFLICT (key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    source_kind = EXCLUDED.source_kind,
    trust_level = EXCLUDED.trust_level,
    verified = EXCLUDED.verified,
    notes = EXCLUDED.notes;

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
        SELECT
            bioguide_id,
            external_ids
        FROM public.politicians
        WHERE id = p_politician_id
    )
    SELECT 'bioguide', 'bioguide_id', btrim(p.bioguide_id), 10
    FROM p
    WHERE NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL

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
        CASE
            WHEN jsonb_typeof(p.external_ids -> 'fec') = 'array' THEN p.external_ids -> 'fec'
            ELSE '[]'::jsonb
        END
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

CREATE OR REPLACE FUNCTION public.sync_legacy_profile_identity(p_politician_id uuid)
RETURNS TABLE (
    person_id uuid,
    legacy_politician_id uuid,
    resolution_method text
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    identity_namespace constant uuid := '6fb3f3e2-0f6f-42f4-b7e9-d8ed15ed8d2f';
    existing_person_id uuid;
    target_person_id uuid;
    target_method text := 'legacy_singleton';
    legacy_name text;
    canonical_legacy_id uuid;
    first_identity_key text;
BEGIN
    SELECT p.full_name
    INTO legacy_name
    FROM public.politicians AS p
    WHERE p.id = p_politician_id;

    IF legacy_name IS NULL THEN
        RETURN;
    END IF;

    SELECT l.person_id
    INTO existing_person_id
    FROM public.legacy_profile_redirects AS l
    WHERE l.legacy_politician_id = p_politician_id;

    SELECT pei.person_id
    INTO target_person_id
    FROM public.get_legacy_profile_identity_keys(p_politician_id) AS k
    JOIN public.person_external_ids AS pei
      ON pei.source_system_key = k.source_system_key
     AND pei.external_id_type = k.external_id_type
     AND pei.external_id = k.external_id
    JOIN public.people AS pe ON pe.id = pei.person_id
    WHERE pe.status = 'active'
    ORDER BY k.priority, pei.created_at, pei.person_id
    LIMIT 1;

    IF target_person_id IS NOT NULL THEN
        target_method := 'deterministic_external_id';
    END IF;

    IF target_person_id IS NULL THEN
        SELECT
            min(
                k.source_system_key || ':' || k.external_id_type || ':' || k.external_id
            )
        INTO first_identity_key
        FROM public.get_legacy_profile_identity_keys(p_politician_id) AS k;

        IF first_identity_key IS NOT NULL THEN
            target_person_id := uuid_generate_v5(identity_namespace, 'identity:' || first_identity_key);
            target_method := 'deterministic_external_id';
        ELSE
            target_person_id := uuid_generate_v5(
                identity_namespace,
                'legacy:' || p_politician_id::text
            );
            target_method := 'legacy_singleton';
        END IF;
    END IF;

    IF existing_person_id IS NOT NULL AND existing_person_id <> target_person_id THEN
        INSERT INTO public.identity_resolution_candidates (
            candidate_type,
            source_legacy_politician_id,
            source_person_id,
            candidate_person_id,
            status,
            evidence
        ) VALUES (
            'deterministic_redirect_conflict',
            p_politician_id,
            existing_person_id,
            target_person_id,
            'blocked',
            jsonb_build_object(
                'reason', 'Existing legacy redirect points at a different person than deterministic identity keys.',
                'legacy_politician_id', p_politician_id
            )
        )
        ON CONFLICT DO NOTHING;

        target_person_id := existing_person_id;
        target_method := 'existing_legacy_redirect';
    END IF;

    INSERT INTO public.people (
        id,
        primary_name,
        display_name,
        status
    ) VALUES (
        target_person_id,
        legacy_name,
        legacy_name,
        'active'
    )
    ON CONFLICT (id) DO UPDATE SET
        primary_name = COALESCE(public.people.primary_name, EXCLUDED.primary_name),
        display_name = COALESCE(public.people.display_name, EXCLUDED.display_name),
        status = CASE
            WHEN public.people.status = 'merged' THEN public.people.status
            ELSE 'active'
        END;

    SELECT COALESCE(l.canonical_politician_id, p_politician_id)
    INTO canonical_legacy_id
    FROM public.legacy_profile_redirects AS l
    WHERE l.person_id = target_person_id
    ORDER BY (l.canonical_politician_id IS NOT NULL) DESC, l.created_at, l.legacy_politician_id
    LIMIT 1;

    INSERT INTO public.legacy_profile_redirects (
        legacy_politician_id,
        person_id,
        canonical_politician_id,
        resolution_method,
        confidence
    ) VALUES (
        p_politician_id,
        target_person_id,
        COALESCE(canonical_legacy_id, p_politician_id),
        target_method,
        1.000
    )
    ON CONFLICT (legacy_politician_id) DO UPDATE SET
        person_id = EXCLUDED.person_id,
        canonical_politician_id = EXCLUDED.canonical_politician_id,
        resolution_method = EXCLUDED.resolution_method,
        confidence = EXCLUDED.confidence;

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
        target_person_id,
        'avanguardia-legacy-profile',
        p_politician_id,
        legacy_name,
        public.normalize_identity_name(legacy_name),
        'profile_name',
        true
    WHERE public.normalize_identity_name(legacy_name) IS NOT NULL
    ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO UPDATE SET
        is_primary = public.person_names.is_primary OR EXCLUDED.is_primary;

    INSERT INTO public.person_external_ids (
        person_id,
        source_system_key,
        external_id_type,
        external_id,
        is_trusted,
        source_legacy_politician_id
    )
    SELECT
        target_person_id,
        'avanguardia-legacy-profile',
        'politicians.id',
        p_politician_id::text,
        true,
        p_politician_id
    ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
        person_id = EXCLUDED.person_id,
        source_legacy_politician_id = EXCLUDED.source_legacy_politician_id;

    INSERT INTO public.person_external_ids (
        person_id,
        source_system_key,
        external_id_type,
        external_id,
        is_trusted,
        source_legacy_politician_id
    )
    SELECT DISTINCT
        target_person_id,
        k.source_system_key,
        k.external_id_type,
        k.external_id,
        true,
        p_politician_id
    FROM public.get_legacy_profile_identity_keys(p_politician_id) AS k
    ON CONFLICT (source_system_key, external_id_type, external_id) DO NOTHING;

    RETURN QUERY
    SELECT target_person_id, p_politician_id, target_method;
END;
$$;

DROP TABLE IF EXISTS _canonical_identity_backfill;

CREATE TEMP TABLE _canonical_identity_backfill
ON COMMIT DROP
AS
WITH RECURSIVE
base_profiles AS (
    SELECT id
    FROM public.politicians
),
identity_keys AS (
    SELECT
        p.id AS politician_id,
        k.source_system_key,
        k.external_id_type,
        k.external_id,
        k.priority
    FROM base_profiles AS p
    CROSS JOIN LATERAL public.get_legacy_profile_identity_keys(p.id) AS k
),
edges AS (
    SELECT id AS left_id, id AS right_id
    FROM base_profiles
    UNION
    SELECT a.politician_id, b.politician_id
    FROM identity_keys AS a
    JOIN identity_keys AS b
      ON b.source_system_key = a.source_system_key
     AND b.external_id_type = a.external_id_type
     AND b.external_id = a.external_id
),
walk(root_id, politician_id) AS (
    SELECT id, id
    FROM base_profiles
    UNION
    SELECT w.root_id, e.right_id
    FROM walk AS w
    JOIN edges AS e ON e.left_id = w.politician_id
),
components AS (
    SELECT
        politician_id,
        min(root_id::text)::uuid AS component_id
    FROM walk
    GROUP BY politician_id
),
component_identity_keys AS (
    SELECT
        c.component_id,
        min(k.source_system_key || ':' || k.external_id_type || ':' || k.external_id) AS first_identity_key,
        count(DISTINCT k.source_system_key || ':' || k.external_id_type || ':' || k.external_id) AS identity_key_count
    FROM components AS c
    JOIN identity_keys AS k ON k.politician_id = c.politician_id
    GROUP BY c.component_id
),
component_counts AS (
    SELECT
        c.component_id,
        count(*) AS profile_count
    FROM components AS c
    GROUP BY c.component_id
),
profile_scores AS (
    SELECT
        c.component_id,
        p.id AS legacy_politician_id,
        p.full_name,
        p.last_updated,
        (
            CASE WHEN NULLIF(btrim(coalesce(p.bioguide_id, '')), '') IS NOT NULL THEN 100000 ELSE 0 END
          + CASE WHEN p.external_ids ? 'openstates' THEN 80000 ELSE 0 END
          + CASE WHEN p.external_ids ? 'govtrack' THEN 70000 ELSE 0 END
          + CASE WHEN p.external_ids ? 'wikidata' THEN 60000 ELSE 0 END
          + CASE WHEN p.external_ids ? 'fec' THEN 50000 ELSE 0 END
          + CASE WHEN ci.politician_id IS NOT NULL THEN 1000 ELSE 0 END
          + COALESCE(fd.row_count, 0) * 25
          + COALESCE(cd.row_count, 0)
          + COALESCE(vr.row_count, 0)
          + COALESCE(um.row_count, 0)
          + COALESCE(rel.row_count, 0) * 5
        ) AS richness_score
    FROM components AS c
    JOIN public.politicians AS p ON p.id = c.politician_id
    LEFT JOIN public.contact_info AS ci ON ci.politician_id = p.id
    LEFT JOIN LATERAL (
        SELECT count(*) AS row_count
        FROM public.financial_disclosures AS fd
        WHERE fd.politician_id = p.id
    ) AS fd ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS row_count
        FROM public.campaign_donors AS cd
        WHERE cd.politician_id = p.id
    ) AS cd ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS row_count
        FROM public.voting_records AS vr
        WHERE vr.politician_id = p.id
    ) AS vr ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS row_count
        FROM public.unconfirmed_mentions AS um
        WHERE um.politician_id = p.id
    ) AS um ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS row_count
        FROM public.relationships AS rel
        WHERE rel.politician_id = p.id
    ) AS rel ON true
),
ranked_profiles AS (
    SELECT
        ps.*,
        row_number() OVER (
            PARTITION BY ps.component_id
            ORDER BY ps.richness_score DESC, ps.last_updated DESC NULLS LAST, ps.legacy_politician_id
        ) AS profile_rank
    FROM profile_scores AS ps
),
component_people AS (
    SELECT
        cc.component_id,
        uuid_generate_v5(
            '6fb3f3e2-0f6f-42f4-b7e9-d8ed15ed8d2f'::uuid,
            CASE
                WHEN cik.first_identity_key IS NOT NULL THEN 'identity:' || cik.first_identity_key
                ELSE 'legacy:' || cc.component_id::text
            END
        ) AS person_id,
        rp.legacy_politician_id AS canonical_politician_id,
        rp.full_name AS primary_name,
        COALESCE(cik.identity_key_count, 0) AS identity_key_count,
        counts.profile_count
    FROM (SELECT DISTINCT component_id FROM components) AS cc
    JOIN component_counts AS counts ON counts.component_id = cc.component_id
    JOIN ranked_profiles AS rp ON rp.component_id = cc.component_id AND rp.profile_rank = 1
    LEFT JOIN component_identity_keys AS cik ON cik.component_id = cc.component_id
)
SELECT
    c.politician_id AS legacy_politician_id,
    cp.person_id,
    cp.canonical_politician_id,
    cp.primary_name,
    CASE
        WHEN cp.identity_key_count > 0 THEN 'deterministic_external_id'
        ELSE 'legacy_singleton'
    END AS resolution_method,
    CASE
        WHEN cp.identity_key_count > 0 THEN 1.000::numeric(4, 3)
        ELSE 0.900::numeric(4, 3)
    END AS confidence,
    cp.profile_count
FROM components AS c
JOIN component_people AS cp ON cp.component_id = c.component_id;

INSERT INTO public.people (
    id,
    primary_name,
    display_name,
    status
)
SELECT DISTINCT ON (b.person_id)
    b.person_id,
    b.primary_name,
    b.primary_name,
    'active'
FROM _canonical_identity_backfill AS b
ORDER BY b.person_id, b.profile_count DESC, b.canonical_politician_id
ON CONFLICT (id) DO UPDATE SET
    primary_name = EXCLUDED.primary_name,
    display_name = EXCLUDED.display_name,
    status = CASE
        WHEN public.people.status = 'merged' THEN public.people.status
        ELSE 'active'
    END;

INSERT INTO public.legacy_profile_redirects (
    legacy_politician_id,
    person_id,
    canonical_politician_id,
    resolution_method,
    confidence
)
SELECT
    legacy_politician_id,
    person_id,
    canonical_politician_id,
    resolution_method,
    confidence
FROM _canonical_identity_backfill
ON CONFLICT (legacy_politician_id) DO UPDATE SET
    person_id = EXCLUDED.person_id,
    canonical_politician_id = EXCLUDED.canonical_politician_id,
    resolution_method = EXCLUDED.resolution_method,
    confidence = EXCLUDED.confidence;

INSERT INTO public.person_external_ids (
    person_id,
    source_system_key,
    external_id_type,
    external_id,
    is_trusted,
    source_legacy_politician_id
)
SELECT
    b.person_id,
    'avanguardia-legacy-profile',
    'politicians.id',
    b.legacy_politician_id::text,
    true,
    b.legacy_politician_id
FROM _canonical_identity_backfill AS b
ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
    person_id = EXCLUDED.person_id,
    source_legacy_politician_id = EXCLUDED.source_legacy_politician_id;

INSERT INTO public.person_external_ids (
    person_id,
    source_system_key,
    external_id_type,
    external_id,
    is_trusted,
    source_legacy_politician_id
)
SELECT DISTINCT
    b.person_id,
    k.source_system_key,
    k.external_id_type,
    k.external_id,
    true,
    b.legacy_politician_id
FROM _canonical_identity_backfill AS b
CROSS JOIN LATERAL public.get_legacy_profile_identity_keys(b.legacy_politician_id) AS k
ON CONFLICT (source_system_key, external_id_type, external_id) DO UPDATE SET
    person_id = EXCLUDED.person_id,
    source_legacy_politician_id = EXCLUDED.source_legacy_politician_id;

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
    b.person_id,
    'avanguardia-legacy-profile',
    p.id,
    p.full_name,
    public.normalize_identity_name(p.full_name),
    'profile_name',
    p.id = b.canonical_politician_id
FROM _canonical_identity_backfill AS b
JOIN public.politicians AS p ON p.id = b.legacy_politician_id
WHERE public.normalize_identity_name(p.full_name) IS NOT NULL
ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO UPDATE SET
    is_primary = public.person_names.is_primary OR EXCLUDED.is_primary;

INSERT INTO public.person_names (
    person_id,
    source_system_key,
    legacy_politician_id,
    name_text,
    normalized_name,
    name_type,
    is_primary
)
SELECT DISTINCT
    b.person_id,
    'avanguardia-legacy-profile',
    p.id,
    alias_name,
    public.normalize_identity_name(alias_name),
    'alias',
    false
FROM _canonical_identity_backfill AS b
JOIN public.politicians AS p ON p.id = b.legacy_politician_id
CROSS JOIN LATERAL unnest(p.aliases) AS alias_name
WHERE public.normalize_identity_name(alias_name) IS NOT NULL
ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO NOTHING;

WITH mapped_profiles AS (
    SELECT
        l.legacy_politician_id,
        l.person_id,
        p.full_name,
        public.normalize_identity_name(p.full_name) AS normalized_name
    FROM public.legacy_profile_redirects AS l
    JOIN public.politicians AS p ON p.id = l.legacy_politician_id
),
same_name_pairs AS (
    SELECT
        a.legacy_politician_id AS source_legacy_politician_id,
        b.legacy_politician_id AS candidate_legacy_politician_id,
        a.person_id AS source_person_id,
        b.person_id AS candidate_person_id,
        a.normalized_name,
        EXISTS (
            SELECT 1 FROM public.get_legacy_profile_identity_keys(a.legacy_politician_id)
        ) AS source_has_deterministic_id,
        EXISTS (
            SELECT 1 FROM public.get_legacy_profile_identity_keys(b.legacy_politician_id)
        ) AS candidate_has_deterministic_id
    FROM mapped_profiles AS a
    JOIN mapped_profiles AS b
      ON b.normalized_name = a.normalized_name
     AND b.person_id <> a.person_id
     AND b.legacy_politician_id > a.legacy_politician_id
    WHERE a.normalized_name IS NOT NULL
)
INSERT INTO public.identity_resolution_candidates (
    candidate_type,
    source_legacy_politician_id,
    candidate_legacy_politician_id,
    source_person_id,
    candidate_person_id,
    status,
    score,
    evidence
)
SELECT
    CASE
        WHEN source_has_deterministic_id AND candidate_has_deterministic_id
            THEN 'same_name_conflicting_deterministic_ids'
        ELSE 'same_name_review'
    END,
    source_legacy_politician_id,
    candidate_legacy_politician_id,
    source_person_id,
    candidate_person_id,
    'pending',
    CASE
        WHEN source_has_deterministic_id AND candidate_has_deterministic_id THEN 0.300
        ELSE 0.100
    END,
    jsonb_build_object(
        'normalized_name', normalized_name,
        'rule', 'Same normalized name is review-only and never an automatic merge.'
    )
FROM same_name_pairs
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION public.get_canonical_person_legacy_ids(profile_id uuid)
RETURNS TABLE (
    person_id uuid,
    legacy_politician_id uuid,
    is_canonical boolean
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH resolved AS (
        SELECT
            1 AS priority,
            COALESCE(pe.merged_into_person_id, pe.id) AS person_id
        FROM public.people AS pe
        WHERE pe.id = profile_id
          AND pe.status IN ('active', 'merged')

        UNION ALL

        SELECT
            2 AS priority,
            l.person_id
        FROM public.legacy_profile_redirects AS l
        JOIN public.people AS pe ON pe.id = l.person_id
        WHERE l.legacy_politician_id = profile_id
          AND pe.status = 'active'
    ),
    chosen AS (
        SELECT r.person_id
        FROM resolved AS r
        ORDER BY r.priority
        LIMIT 1
    ),
    mapped AS (
        SELECT
            l.person_id,
            l.legacy_politician_id,
            l.legacy_politician_id = l.canonical_politician_id AS is_canonical
        FROM chosen AS c
        JOIN public.legacy_profile_redirects AS l ON l.person_id = c.person_id
    ),
    fallback AS (
        SELECT
            profile_id AS person_id,
            profile_id AS legacy_politician_id,
            true AS is_canonical
        WHERE NOT EXISTS (SELECT 1 FROM mapped)
          AND EXISTS (
              SELECT 1
              FROM public.politicians AS p
              WHERE p.id = profile_id
          )
    )
    SELECT * FROM mapped
    UNION ALL
    SELECT * FROM fallback;
$$;

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
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
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
        rp.current_office,
        rp.party,
        rp.state,
        rp.district,
        rp.last_updated
    FROM ranked_profiles AS rp
    LEFT JOIN public.people AS pe ON pe.id = rp.person_id AND pe.status = 'active'
    WHERE rp.profile_rank = 1
    LIMIT 1;
$$;

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
    WITH params AS (
        SELECT NULLIF(btrim(search_query), '') AS q
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

        SELECT
            p.id AS person_id,
            p.id AS legacy_politician_id,
            true AS is_canonical
        FROM public.politicians AS p
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.legacy_profile_redirects AS l
            WHERE l.legacy_politician_id = p.id
        )
    ),
    matching_people AS (
        SELECT
            mp.person_id,
            bool_or(
                params.q IS NULL
                OR COALESCE(p.search_vector @@ websearch_to_tsquery('english', params.q), false)
                OR COALESCE(to_tsvector('english', coalesce(pe.primary_name, '')) @@ websearch_to_tsquery('english', params.q), false)
            ) AS matches_search
        FROM mapped_profiles AS mp
        JOIN public.politicians AS p ON p.id = mp.legacy_politician_id
        LEFT JOIN public.people AS pe ON pe.id = mp.person_id
        CROSS JOIN params
        GROUP BY mp.person_id
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
        rp.current_office,
        rp.party,
        rp.state,
        rp.district,
        rp.government_level,
        rp.government_branch,
        rp.office_type,
        rp.jurisdiction
    FROM matching_people AS m
    JOIN ranked_profiles AS rp
      ON rp.person_id = m.person_id
     AND rp.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = rp.person_id AND pe.status = 'active'
    WHERE m.matches_search
    ORDER BY COALESCE(pe.primary_name, rp.full_name), rp.person_id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 1000), 0), 1000)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_contact_info(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    office_address text,
    phone_number text,
    official_website text,
    last_updated timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        ci.politician_id,
        ci.office_address,
        ci.phone_number,
        ci.official_website,
        ci.last_updated
    FROM public.contact_info AS ci
    JOIN legacy AS l ON l.legacy_politician_id = ci.politician_id
    ORDER BY l.is_canonical DESC, ci.last_updated DESC NULLS LAST, ci.politician_id
    LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_financial_disclosures(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    filing_date date,
    filing_type text,
    doc_url text,
    doc_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        fd.id,
        fd.filing_date,
        fd.filing_type,
        fd.doc_url,
        fd.doc_id
    FROM public.financial_disclosures AS fd
    JOIN legacy AS l ON l.legacy_politician_id = fd.politician_id
    ORDER BY fd.filing_date DESC, fd.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_campaign_donors(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    donation_date date,
    donor_name text,
    pac_status boolean,
    amount numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        cd.id,
        cd.donation_date,
        cd.donor_name,
        cd.pac_status,
        cd.amount
    FROM public.campaign_donors AS cd
    JOIN legacy AS l ON l.legacy_politician_id = cd.politician_id
    ORDER BY cd.donation_date DESC NULLS LAST, cd.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_voting_records(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0,
    vote_cast_filter text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    bill_name text,
    bill_summary text,
    vote_date date,
    vote_cast text,
    jurisdiction text,
    roll_call_id text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        vr.id,
        vr.bill_name,
        vr.bill_summary,
        vr.vote_date,
        vr.vote_cast,
        vr.jurisdiction,
        vr.roll_call_id
    FROM public.voting_records AS vr
    JOIN legacy AS l ON l.legacy_politician_id = vr.politician_id
    WHERE NULLIF(btrim(coalesce(vote_cast_filter, '')), '') IS NULL
       OR vr.vote_cast = vote_cast_filter
    ORDER BY vr.vote_date DESC, vr.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_canonical_media_mentions(
    p_id uuid,
    result_limit integer DEFAULT 26,
    result_offset integer DEFAULT 0
)
RETURNS TABLE (
    id uuid,
    source_api text,
    sentiment_score numeric,
    content_summary text,
    url text,
    created_at timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH legacy AS (
        SELECT legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        um.id,
        um.source_api,
        um.sentiment_score,
        um.content_summary,
        um.url,
        um.created_at
    FROM public.unconfirmed_mentions AS um
    JOIN legacy AS l ON l.legacy_politician_id = um.politician_id
    ORDER BY um.created_at DESC NULLS LAST, um.id
    LIMIT LEAST(GREATEST(COALESCE(result_limit, 26), 0), 101)
    OFFSET GREATEST(COALESCE(result_offset, 0), 0);
$$;

CREATE OR REPLACE FUNCTION public.get_shared_donors(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    shared_donor_count bigint,
    shared_total_amount numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH target_legacy AS (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target_person AS (
        SELECT person_id
        FROM target_legacy
        LIMIT 1
    ),
    mine AS (
        SELECT DISTINCT lower(btrim(cd.donor_name)) AS dn
        FROM public.campaign_donors AS cd
        JOIN target_legacy AS tl ON tl.legacy_politician_id = cd.politician_id
        WHERE cd.donor_name IS NOT NULL
          AND btrim(cd.donor_name) <> ''
    ),
    other_donors AS (
        SELECT
            om.person_id,
            cd.donor_name,
            cd.amount
        FROM public.campaign_donors AS cd
        JOIN public.legacy_profile_redirects AS om ON om.legacy_politician_id = cd.politician_id
        JOIN target_person AS tp ON tp.person_id <> om.person_id
        JOIN mine ON mine.dn = lower(btrim(cd.donor_name))
    ),
    ranked_headers AS (
        SELECT
            l.person_id,
            p.full_name,
            p.current_office,
            p.party,
            row_number() OVER (
                PARTITION BY l.person_id
                ORDER BY
                    (l.legacy_politician_id = l.canonical_politician_id) DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM public.legacy_profile_redirects AS l
        JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        od.person_id AS politician_id,
        COALESCE(pe.primary_name, rh.full_name) AS full_name,
        rh.current_office,
        rh.party,
        count(DISTINCT lower(btrim(od.donor_name))) AS shared_donor_count,
        COALESCE(sum(od.amount), 0) AS shared_total_amount
    FROM other_donors AS od
    JOIN ranked_headers AS rh ON rh.person_id = od.person_id AND rh.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = od.person_id AND pe.status = 'active'
    GROUP BY od.person_id, COALESCE(pe.primary_name, rh.full_name), rh.current_office, rh.party
    ORDER BY shared_donor_count DESC, shared_total_amount DESC
    LIMIT 15;
$$;

CREATE OR REPLACE FUNCTION public.get_covoting(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    agree_count bigint,
    disagree_count bigint,
    shared_total bigint,
    agreement_rate numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH target_legacy AS (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target_person AS (
        SELECT person_id
        FROM target_legacy
        LIMIT 1
    ),
    mine AS (
        SELECT DISTINCT ON (vr.roll_call_id)
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN target_legacy AS tl ON tl.legacy_politician_id = vr.politician_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
        ORDER BY vr.roll_call_id, vr.vote_cast
    ),
    theirs AS (
        SELECT DISTINCT ON (om.person_id, vr.roll_call_id)
            om.person_id,
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN public.legacy_profile_redirects AS om ON om.legacy_politician_id = vr.politician_id
        JOIN target_person AS tp ON tp.person_id <> om.person_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
        ORDER BY om.person_id, vr.roll_call_id, vr.vote_cast
    ),
    ranked_headers AS (
        SELECT
            l.person_id,
            p.full_name,
            p.current_office,
            p.party,
            row_number() OVER (
                PARTITION BY l.person_id
                ORDER BY
                    (l.legacy_politician_id = l.canonical_politician_id) DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM public.legacy_profile_redirects AS l
        JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        theirs.person_id AS politician_id,
        COALESCE(pe.primary_name, rh.full_name) AS full_name,
        rh.current_office,
        rh.party,
        count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast) AS agree_count,
        count(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast) AS disagree_count,
        count(*) AS shared_total,
        round(
            count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast)::numeric
            / NULLIF(count(*), 0),
            3
        ) AS agreement_rate
    FROM theirs
    JOIN mine ON mine.roll_call_id = theirs.roll_call_id
    JOIN ranked_headers AS rh ON rh.person_id = theirs.person_id AND rh.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = theirs.person_id AND pe.status = 'active'
    GROUP BY theirs.person_id, COALESCE(pe.primary_name, rh.full_name), rh.current_office, rh.party
    ORDER BY shared_total DESC, GREATEST(
        count(*) FILTER (WHERE theirs.vote_cast = mine.vote_cast),
        count(*) FILTER (WHERE theirs.vote_cast <> mine.vote_cast)
    ) DESC
    LIMIT 30;
$$;

CREATE OR REPLACE FUNCTION public.get_network_ties(p_id uuid)
RETURNS TABLE (
    related_name text,
    related_politician_id uuid,
    relationship_type text,
    source_api text,
    url text
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH target_legacy AS (
        SELECT legacy_politician_id
        FROM public.get_canonical_person_legacy_ids(p_id)
    )
    SELECT
        r.related_name,
        COALESCE(related.person_id, r.related_politician_id) AS related_politician_id,
        r.relationship_type,
        r.source_api,
        r.url
    FROM public.relationships AS r
    JOIN target_legacy AS tl ON tl.legacy_politician_id = r.politician_id
    LEFT JOIN public.legacy_profile_redirects AS related
      ON related.legacy_politician_id = r.related_politician_id
    ORDER BY (COALESCE(related.person_id, r.related_politician_id) IS NULL), r.related_name
    LIMIT 30;
$$;

CREATE OR REPLACE VIEW public.identity_validation_duplicate_external_ids AS
SELECT
    source_system_key,
    external_id_type,
    external_id,
    count(DISTINCT person_id) AS person_count,
    array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids
FROM public.person_external_ids
GROUP BY source_system_key, external_id_type, external_id
HAVING count(DISTINCT person_id) > 1;

CREATE OR REPLACE VIEW public.identity_validation_unmapped_legacy_profiles AS
SELECT
    p.id AS legacy_politician_id,
    p.full_name,
    p.current_office,
    p.last_updated
FROM public.politicians AS p
LEFT JOIN public.legacy_profile_redirects AS l ON l.legacy_politician_id = p.id
WHERE l.legacy_politician_id IS NULL;

CREATE OR REPLACE VIEW public.identity_validation_pending_candidates AS
SELECT
    id,
    candidate_type,
    source_legacy_politician_id,
    candidate_legacy_politician_id,
    source_person_id,
    candidate_person_id,
    status,
    score,
    evidence,
    created_at,
    updated_at
FROM public.identity_resolution_candidates
WHERE status = 'pending';

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'source_systems',
        'people',
        'person_external_ids',
        'person_names',
        'legacy_profile_redirects',
        'identity_resolution_candidates',
        'person_merge_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated;', t);
    END LOOP;
END $$;

REVOKE ALL ON TABLE public.identity_validation_duplicate_external_ids FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.identity_validation_unmapped_legacy_profiles FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.identity_validation_pending_candidates FROM PUBLIC, anon, authenticated;

REVOKE EXECUTE ON FUNCTION public.set_updated_at() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.normalize_identity_name(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_legacy_profile_identity_keys(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.sync_legacy_profile_identity(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_person_legacy_ids(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_contact_info(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_financial_disclosures(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_campaign_donors(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records(uuid, integer, integer, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_canonical_media_mentions(uuid, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_shared_donors(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_covoting(uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.get_network_ties(uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.sync_legacy_profile_identity(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_canonical_person_legacy_ids(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_politician_summaries(text, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_politician_header(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_contact_info(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_financial_disclosures(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_campaign_donors(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_voting_records(uuid, integer, integer, text) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_canonical_media_mentions(uuid, integer, integer) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_shared_donors(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_covoting(uuid) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_network_ties(uuid) TO anon, authenticated;

NOTIFY pgrst, 'reload schema';
