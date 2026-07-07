-- 0015_openstates_federal_duplicate_cleanup.sql
--
-- Resolve the deterministic duplicate people caused by OpenStates `data/us` records
-- being ingested as state officials before PR60 excluded that dataset. The bad
-- legacy profile UUIDs are preserved through redirects; only the canonical person
-- mapping, identity metadata, and review status are moved to the existing federal
-- survivor. Stale duplicate spoke rows are deleted so canonical reads do not show
-- bad OpenStates federal-as-state profile data.

SET statement_timeout = '30s';

DROP TABLE IF EXISTS _0015_openstates_federal_duplicate_targets;

CREATE TEMP TABLE _0015_openstates_federal_duplicate_targets
ON COMMIT DROP
AS
WITH observer_candidates AS (
    SELECT
        c.id AS candidate_id,
        c.source_legacy_politician_id AS stale_legacy_politician_id,
        c.source_person_id AS stale_person_id,
        p.full_name,
        p.current_office,
        max(k.value ->> 'external_id') FILTER (
            WHERE k.value ->> 'source_system_key' = 'bioguide'
              AND k.value ->> 'external_id_type' = 'bioguide_id'
        ) AS bioguide_id,
        max(k.value ->> 'external_id') FILTER (
            WHERE k.value ->> 'source_system_key' = 'openstates'
              AND k.value ->> 'external_id_type' = 'openstates_person_id'
        ) AS openstates_person_id
    FROM public.identity_resolution_candidates AS c
    JOIN public.politicians AS p
      ON p.id = c.source_legacy_politician_id
    CROSS JOIN LATERAL jsonb_array_elements(c.evidence -> 'deterministic_keys') AS k(value)
    WHERE c.candidate_type = 'identity_observer_blocked_deterministic_keys_match_multiple_people'
      AND c.status = 'pending'
      AND c.source_legacy_politician_id = c.candidate_legacy_politician_id
      AND c.source_person_id IS NOT NULL
      AND (
          p.current_office LIKE 'State Representative from US District%'
          OR p.current_office LIKE 'State Senator from US District%'
      )
    GROUP BY
        c.id,
        c.source_legacy_politician_id,
        c.source_person_id,
        p.full_name,
        p.current_office
),
targets AS (
    SELECT
        oc.candidate_id,
        oc.stale_legacy_politician_id,
        oc.stale_person_id,
        oc.full_name,
        oc.current_office,
        oc.bioguide_id,
        oc.openstates_person_id,
        survivor.person_id AS survivor_person_id,
        survivor.source_legacy_politician_id AS survivor_legacy_politician_id,
        survivor_redirect.canonical_politician_id AS survivor_canonical_politician_id
    FROM observer_candidates AS oc
    JOIN public.legacy_profile_redirects AS stale_redirect
      ON stale_redirect.legacy_politician_id = oc.stale_legacy_politician_id
     AND stale_redirect.person_id = oc.stale_person_id
    JOIN public.people AS stale_person
      ON stale_person.id = oc.stale_person_id
     AND stale_person.status = 'active'
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
    JOIN public.identity_resolution_candidates AS c
      ON c.id = oc.candidate_id
     AND (c.evidence -> 'matching_person_ids') ? oc.stale_person_id::text
     AND (c.evidence -> 'matching_person_ids') ? survivor.person_id::text
    WHERE oc.bioguide_id IS NOT NULL
      AND oc.openstates_person_id IS NOT NULL
)
SELECT *
FROM targets;

DO $$
DECLARE
    duplicate_target_count integer;
BEGIN
    SELECT count(*)
    INTO duplicate_target_count
    FROM (
        SELECT candidate_id
        FROM _0015_openstates_federal_duplicate_targets
        GROUP BY candidate_id
        HAVING count(*) > 1

        UNION ALL

        SELECT stale_legacy_politician_id
        FROM _0015_openstates_federal_duplicate_targets
        GROUP BY stale_legacy_politician_id
        HAVING count(*) > 1

        UNION ALL

        SELECT stale_person_id
        FROM _0015_openstates_federal_duplicate_targets
        GROUP BY stale_person_id
        HAVING count(*) > 1

    ) AS duplicate_targets;

    IF duplicate_target_count <> 0 THEN
        RAISE EXCEPTION
            '0015 guarded cleanup found % duplicate candidate or stale targets',
            duplicate_target_count;
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
        'migration', '0015_openstates_federal_duplicate_cleanup',
        'identity_resolution_candidate_id', t.candidate_id,
        'stale_legacy_politician_id', t.stale_legacy_politician_id,
        'survivor_legacy_politician_id', t.survivor_legacy_politician_id,
        'bioguide_id', t.bioguide_id,
        'openstates_person_id', t.openstates_person_id,
        'reason', 'OpenStates data/us federal record duplicated an existing federal canonical person.'
    )
FROM _0015_openstates_federal_duplicate_targets AS t
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
JOIN _0015_openstates_federal_duplicate_targets AS t
  ON t.stale_person_id = pei.person_id
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
JOIN _0015_openstates_federal_duplicate_targets AS t
  ON t.stale_person_id = pn.person_id
ON CONFLICT (person_id, source_system_key, normalized_name, name_type) DO UPDATE SET
    is_primary = public.person_names.is_primary OR EXCLUDED.is_primary;

DELETE FROM public.person_names AS pn
USING _0015_openstates_federal_duplicate_targets AS t
WHERE pn.person_id = t.stale_person_id;

UPDATE public.legacy_profile_redirects AS l
SET
    person_id = t.survivor_person_id,
    canonical_politician_id = t.survivor_canonical_politician_id,
    resolution_method = 'openstates_data_us_federal_duplicate_cleanup',
    confidence = 1.000
FROM _0015_openstates_federal_duplicate_targets AS t
WHERE l.legacy_politician_id = t.stale_legacy_politician_id
  AND (
      l.person_id IS DISTINCT FROM t.survivor_person_id
      OR l.canonical_politician_id IS DISTINCT FROM t.survivor_canonical_politician_id
      OR l.resolution_method IS DISTINCT FROM 'openstates_data_us_federal_duplicate_cleanup'
      OR l.confidence IS DISTINCT FROM 1.000
  );

DELETE FROM public.contact_info AS ci
USING _0015_openstates_federal_duplicate_targets AS t
WHERE ci.politician_id = t.stale_legacy_politician_id
   OR ci.person_id = t.stale_person_id;

DELETE FROM public.financial_disclosures AS fd
USING _0015_openstates_federal_duplicate_targets AS t
WHERE fd.politician_id = t.stale_legacy_politician_id
   OR fd.person_id = t.stale_person_id;

DELETE FROM public.campaign_donors AS cd
USING _0015_openstates_federal_duplicate_targets AS t
WHERE cd.politician_id = t.stale_legacy_politician_id
   OR cd.person_id = t.stale_person_id;

DELETE FROM public.voting_records AS vr
USING _0015_openstates_federal_duplicate_targets AS t
WHERE vr.politician_id = t.stale_legacy_politician_id
   OR vr.person_id = t.stale_person_id;

DELETE FROM public.unconfirmed_mentions AS um
USING _0015_openstates_federal_duplicate_targets AS t
WHERE um.politician_id = t.stale_legacy_politician_id
   OR um.person_id = t.stale_person_id;

DELETE FROM public.relationships AS r
USING _0015_openstates_federal_duplicate_targets AS t
WHERE r.politician_id = t.stale_legacy_politician_id
   OR r.person_id = t.stale_person_id;

UPDATE public.people AS pe
SET
    status = 'merged',
    merged_into_person_id = t.survivor_person_id
FROM _0015_openstates_federal_duplicate_targets AS t
WHERE pe.id = t.stale_person_id
  AND (
      pe.status IS DISTINCT FROM 'merged'
      OR pe.merged_into_person_id IS DISTINCT FROM t.survivor_person_id
  );

UPDATE public.identity_resolution_candidates AS c
SET
    status = 'approved',
    candidate_person_id = t.survivor_person_id,
    score = 1.000,
    evidence = c.evidence || jsonb_build_object(
        'cleanup',
        jsonb_build_object(
            'migration', '0015_openstates_federal_duplicate_cleanup',
            'resolved_at', now(),
            'stale_person_id', t.stale_person_id,
            'survivor_person_id', t.survivor_person_id,
            'survivor_legacy_politician_id', t.survivor_legacy_politician_id,
            'survivor_canonical_politician_id', t.survivor_canonical_politician_id,
            'resolution', 'merged OpenStates data/us duplicate into existing Bioguide-backed federal person'
        )
    )
FROM _0015_openstates_federal_duplicate_targets AS t
WHERE c.id = t.candidate_id
  AND c.status = 'pending';

DO $$
DECLARE
    remaining_pending_count integer;
    remaining_unresolved_target_count integer;
    remaining_stale_spoke_count integer;
BEGIN
    SELECT count(*)
    INTO remaining_pending_count
    FROM public.identity_resolution_candidates AS c
    JOIN _0015_openstates_federal_duplicate_targets AS t
      ON t.candidate_id = c.id
    WHERE c.status = 'pending';

    SELECT count(*)
    INTO remaining_unresolved_target_count
    FROM _0015_openstates_federal_duplicate_targets AS t
    JOIN public.people AS pe
      ON pe.id = t.stale_person_id
    JOIN public.legacy_profile_redirects AS l
      ON l.legacy_politician_id = t.stale_legacy_politician_id
    JOIN public.identity_resolution_candidates AS c
      ON c.id = t.candidate_id
    WHERE pe.status IS DISTINCT FROM 'merged'
       OR pe.merged_into_person_id IS DISTINCT FROM t.survivor_person_id
       OR l.person_id IS DISTINCT FROM t.survivor_person_id
       OR l.canonical_politician_id IS DISTINCT FROM t.survivor_canonical_politician_id
       OR c.status IS DISTINCT FROM 'approved'
       OR c.candidate_person_id IS DISTINCT FROM t.survivor_person_id;

    SELECT sum(row_count)
    INTO remaining_stale_spoke_count
    FROM (
        SELECT count(*) AS row_count
        FROM public.contact_info AS ci
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON ci.politician_id = t.stale_legacy_politician_id
          OR ci.person_id = t.stale_person_id

        UNION ALL

        SELECT count(*)
        FROM public.financial_disclosures AS fd
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON fd.politician_id = t.stale_legacy_politician_id
          OR fd.person_id = t.stale_person_id

        UNION ALL

        SELECT count(*)
        FROM public.campaign_donors AS cd
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON cd.politician_id = t.stale_legacy_politician_id
          OR cd.person_id = t.stale_person_id

        UNION ALL

        SELECT count(*)
        FROM public.voting_records AS vr
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON vr.politician_id = t.stale_legacy_politician_id
          OR vr.person_id = t.stale_person_id

        UNION ALL

        SELECT count(*)
        FROM public.unconfirmed_mentions AS um
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON um.politician_id = t.stale_legacy_politician_id
          OR um.person_id = t.stale_person_id

        UNION ALL

        SELECT count(*)
        FROM public.relationships AS r
        JOIN _0015_openstates_federal_duplicate_targets AS t
          ON r.politician_id = t.stale_legacy_politician_id
          OR r.person_id = t.stale_person_id
    ) AS stale_spoke_rows;

    IF remaining_pending_count <> 0 THEN
        RAISE EXCEPTION '0015 cleanup left % target candidates pending', remaining_pending_count;
    END IF;

    IF remaining_unresolved_target_count <> 0 THEN
        RAISE EXCEPTION '0015 cleanup left % target people unresolved', remaining_unresolved_target_count;
    END IF;

    IF COALESCE(remaining_stale_spoke_count, 0) <> 0 THEN
        RAISE EXCEPTION '0015 cleanup left % stale duplicate spoke rows', remaining_stale_spoke_count;
    END IF;
END $$;
