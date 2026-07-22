-- 0026_house_roll_call_provenance.sql
--
-- Private, provenance-rich storage and an atomic write contract for official
-- House Clerk roll calls. This migration deliberately leaves production writes
-- disabled. A separate reviewed runtime change must enable both the catalog
-- write gate and the scraper switch before any source facts are persisted.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_write_status text;
    v_source_writes_enabled text;
    v_endpoint_status text;
    v_endpoint_write_status text;
    v_endpoint_writes_enabled text;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0026_house_roll_call_provenance'
    ) THEN
        RAISE EXCEPTION
            'migration 0026_house_roll_call_provenance is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0025_house_roll_call_source_review'
    ) THEN
        RAISE EXCEPTION
            'migration 0025_house_roll_call_source_review must be applied first'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        status,
        repo_fit,
        metadata ->> 'production_write_status',
        metadata ->> 'production_writes_enabled'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_write_status,
        v_source_writes_enabled
    FROM public.source_catalog_sources
    WHERE slug = 'house-clerk-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog row is missing: house-clerk-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        status,
        metadata ->> 'production_write_status',
        metadata ->> 'production_writes_enabled'
    INTO
        v_endpoint_status,
        v_endpoint_write_status,
        v_endpoint_writes_enabled
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'house-clerk-roll-call-xml'
      AND endpoint_slug = 'evs-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: house-clerk-roll-call-xml.evs-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_source_write_status IS DISTINCT FROM 'disabled_pending_separate_ingestion_review'
       OR v_endpoint_write_status IS DISTINCT FROM 'disabled_pending_separate_ingestion_review'
       OR COALESCE(v_source_writes_enabled, 'false') IS DISTINCT FROM 'false'
       OR COALESCE(v_endpoint_writes_enabled, 'false') IS DISTINCT FROM 'false' THEN
        RAISE EXCEPTION
            'House roll-call provenance expected approved/wired/approved with writes disabled, found %/%/% and %/% (%/%)',
            v_source_status,
            v_source_repo_fit,
            v_endpoint_status,
            v_source_write_status,
            v_endpoint_write_status,
            v_source_writes_enabled,
            v_endpoint_writes_enabled
            USING ERRCODE = '55000';
    END IF;

    PERFORM 1
    FROM public.source_systems
    WHERE key = 'house-clerk'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source system is missing: house-clerk'
            USING ERRCODE = '23503';
    END IF;
END
$migration_preflight$;

CREATE TABLE IF NOT EXISTS public.legislative_roll_calls (
    source_record_id uuid PRIMARY KEY
        REFERENCES public.source_records(id) ON DELETE CASCADE,
    canonical_roll_call_key text NOT NULL,
    chamber text NOT NULL,
    congress integer NOT NULL,
    session smallint NOT NULL,
    congress_year integer NOT NULL,
    roll_call_number integer NOT NULL,
    vote_date date NOT NULL,
    question text NOT NULL,
    vote_result text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.person_roll_call_votes (
    source_record_id uuid PRIMARY KEY
        REFERENCES public.source_records(id) ON DELETE CASCADE,
    roll_call_source_record_id uuid NOT NULL
        REFERENCES public.legislative_roll_calls(source_record_id) ON DELETE CASCADE,
    person_id uuid NOT NULL REFERENCES public.people(id) ON DELETE RESTRICT,
    vote_cast text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (roll_call_source_record_id, person_id)
);

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'legislative_roll_calls_key_not_blank_check'
          AND conrelid = 'public.legislative_roll_calls'::regclass
    ) THEN
        ALTER TABLE public.legislative_roll_calls
            ADD CONSTRAINT legislative_roll_calls_key_not_blank_check
            CHECK (NULLIF(btrim(canonical_roll_call_key), '') IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'legislative_roll_calls_chamber_check'
          AND conrelid = 'public.legislative_roll_calls'::regclass
    ) THEN
        ALTER TABLE public.legislative_roll_calls
            ADD CONSTRAINT legislative_roll_calls_chamber_check
            CHECK (chamber IN ('house', 'senate'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'legislative_roll_calls_number_check'
          AND conrelid = 'public.legislative_roll_calls'::regclass
    ) THEN
        ALTER TABLE public.legislative_roll_calls
            ADD CONSTRAINT legislative_roll_calls_number_check
            CHECK (
                congress > 0
                AND session IN (1, 2)
                AND congress_year BETWEEN 1789 AND 2200
                AND roll_call_number > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'legislative_roll_calls_vote_year_check'
          AND conrelid = 'public.legislative_roll_calls'::regclass
    ) THEN
        ALTER TABLE public.legislative_roll_calls
            ADD CONSTRAINT legislative_roll_calls_vote_year_check
            CHECK (EXTRACT(YEAR FROM vote_date)::integer = congress_year);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'legislative_roll_calls_question_not_blank_check'
          AND conrelid = 'public.legislative_roll_calls'::regclass
    ) THEN
        ALTER TABLE public.legislative_roll_calls
            ADD CONSTRAINT legislative_roll_calls_question_not_blank_check
            CHECK (NULLIF(btrim(question), '') IS NOT NULL);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'person_roll_call_votes_vote_cast_check'
          AND conrelid = 'public.person_roll_call_votes'::regclass
    ) THEN
        ALTER TABLE public.person_roll_call_votes
            ADD CONSTRAINT person_roll_call_votes_vote_cast_check
            CHECK (vote_cast IN ('yea', 'nay', 'present', 'not_voting'));
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_legislative_roll_calls_canonical_key
    ON public.legislative_roll_calls(canonical_roll_call_key, vote_date DESC);

CREATE INDEX IF NOT EXISTS idx_person_roll_call_votes_person_roll_call
    ON public.person_roll_call_votes(person_id, roll_call_source_record_id);

-- Bioguide IDs are canonically uppercase, but this index lets the ingestion
-- boundary recognize and fail safely around any historical mixed-case value.
CREATE INDEX IF NOT EXISTS idx_person_external_ids_bioguide_normalized
    ON public.person_external_ids(upper(btrim(external_id)))
    WHERE source_system_key = 'bioguide'
      AND external_id_type = 'bioguide_id';

DROP TRIGGER IF EXISTS legislative_roll_calls_set_updated_at
    ON public.legislative_roll_calls;
CREATE TRIGGER legislative_roll_calls_set_updated_at
    BEFORE UPDATE ON public.legislative_roll_calls
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS person_roll_call_votes_set_updated_at
    ON public.person_roll_call_votes;
CREATE TRIGGER person_roll_call_votes_set_updated_at
    BEFORE UPDATE ON public.person_roll_call_votes
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.legislative_roll_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.person_roll_call_votes ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.legislative_roll_calls FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.person_roll_call_votes FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.legislative_roll_calls
    TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.person_roll_call_votes
    TO service_role;

-- One call ingests one complete roll call and all of its member votes. Any
-- identity miss, malformed key, or conflicting prior vote aborts the entire call.
CREATE OR REPLACE FUNCTION public.upsert_house_roll_call(
    p_roll_call jsonb,
    p_member_votes jsonb
)
RETURNS TABLE (
    roll_call_source_record_id uuid,
    member_vote_count integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
#variable_conflict use_column
DECLARE
    v_congress integer;
    v_session smallint;
    v_congress_year integer;
    v_roll_call_number integer;
    v_vote_date date;
    v_question text;
    v_vote_result text;
    v_source_url text;
    v_payload_hash text;
    v_fetched_at timestamptz;
    v_roll_call_key text;
    v_supplied_roll_call_key text;
    v_url_parts text[];
    v_roll_call_source_record_id uuid;
    v_existing_record_type text;
    v_existing_record_person_id uuid;
    v_existing_catalog_slug text;
    v_existing_endpoint_slug text;
    v_existing_roll_call_key text;
    v_existing_chamber text;
    v_existing_congress integer;
    v_existing_session smallint;
    v_existing_congress_year integer;
    v_existing_roll_call_number integer;
    v_member jsonb;
    v_bioguide_id text;
    v_vote_cast text;
    v_member_key text;
    v_supplied_member_key text;
    v_supplied_bioguide_ids text[];
    v_person_id uuid;
    v_person_status text;
    v_identity_is_trusted boolean;
    v_identity_match_count integer;
    v_gate_source_status text;
    v_gate_source_repo_fit text;
    v_gate_source_writes_enabled text;
    v_gate_endpoint_status text;
    v_gate_endpoint_writes_enabled text;
    v_member_source_record_id uuid;
    v_existing_vote_source_record_id uuid;
    v_existing_vote_roll_call_id uuid;
    v_existing_vote_person_id uuid;
    v_existing_vote_cast text;
    v_member_count integer;
BEGIN
    -- Non-mutating schema-preflight probe.
    IF jsonb_typeof(p_roll_call) = 'object'
       AND COALESCE(p_roll_call ->> 'preflight', '') = 'true'
       AND p_member_votes = '[]'::jsonb THEN
        RETURN QUERY SELECT NULL::uuid, 0::integer;
        RETURN;
    END IF;

    IF jsonb_typeof(p_roll_call) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'roll_call must be a JSON object' USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(p_member_votes) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'member_votes must be a JSON array' USING ERRCODE = '22023';
    END IF;

    v_member_count := jsonb_array_length(p_member_votes);
    IF v_member_count = 0 THEN
        RAISE EXCEPTION 'member_votes must contain at least one vote'
            USING ERRCODE = '22023';
    END IF;
    IF v_member_count > 1000 THEN
        RAISE EXCEPTION 'member_votes exceeds the bounded per-roll-call limit'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'bioguide_id'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'vote_cast'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '') IS NULL
    ) THEN
        RAISE EXCEPTION
            'every member vote must be an object with bioguide_id, vote_cast, and source_record_key'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT upper(btrim(item.value ->> 'bioguide_id')))
        FROM jsonb_array_elements(p_member_votes) AS item(value)
    ) <> v_member_count THEN
        RAISE EXCEPTION 'member_votes contains duplicate Bioguide IDs'
            USING ERRCODE = '22023';
    END IF;

    SELECT array_agg(
        upper(btrim(item.value ->> 'bioguide_id'))
        ORDER BY upper(btrim(item.value ->> 'bioguide_id'))
    )
    INTO v_supplied_bioguide_ids
    FROM jsonb_array_elements(p_member_votes) AS item(value);

    BEGIN
        v_congress := NULLIF(btrim(p_roll_call ->> 'congress'), '')::integer;
        v_session := NULLIF(btrim(p_roll_call ->> 'session'), '')::smallint;
        v_congress_year := NULLIF(btrim(p_roll_call ->> 'congress_year'), '')::integer;
        v_roll_call_number := NULLIF(btrim(p_roll_call ->> 'roll_call_number'), '')::integer;
        v_vote_date := NULLIF(btrim(p_roll_call ->> 'vote_date'), '')::date;
        v_fetched_at := NULLIF(btrim(p_roll_call ->> 'fetched_at'), '')::timestamptz;
    EXCEPTION
        WHEN invalid_text_representation OR datetime_field_overflow THEN
            RAISE EXCEPTION 'roll_call has an invalid numeric, date, or timestamp field'
                USING ERRCODE = '22023';
    END;

    v_question := NULLIF(btrim(p_roll_call ->> 'question'), '');
    v_vote_result := NULLIF(btrim(p_roll_call ->> 'vote_result'), '');
    v_source_url := NULLIF(btrim(p_roll_call ->> 'source_url'), '');
    v_payload_hash := lower(NULLIF(btrim(p_roll_call ->> 'payload_hash'), ''));
    v_supplied_roll_call_key := NULLIF(
        btrim(p_roll_call ->> 'source_record_key'),
        ''
    );

    IF v_congress IS NULL
       OR v_session IS NULL
       OR v_session NOT IN (1, 2)
       OR v_congress_year IS NULL
       OR v_congress_year NOT BETWEEN 1789 AND 2200
       OR v_roll_call_number IS NULL
       OR v_roll_call_number <= 0
       OR v_vote_date IS NULL
       OR EXTRACT(YEAR FROM v_vote_date)::integer <> v_congress_year
       OR v_question IS NULL
       OR v_source_url IS NULL
       OR v_payload_hash IS NULL
       OR v_fetched_at IS NULL THEN
        RAISE EXCEPTION 'roll_call is missing a required or valid field'
            USING ERRCODE = '22023';
    END IF;

    IF v_congress <= 0 THEN
        RAISE EXCEPTION 'roll_call.congress must be positive'
            USING ERRCODE = '22023';
    END IF;

    IF v_payload_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'roll_call.payload_hash must be a SHA-256 hex digest'
            USING ERRCODE = '22023';
    END IF;

    IF v_fetched_at < v_vote_date::timestamptz
       OR v_fetched_at > now() + interval '5 minutes' THEN
        RAISE EXCEPTION 'roll_call.fetched_at is outside the valid observation window'
            USING ERRCODE = '22023';
    END IF;

    v_roll_call_key := format(
        'house:%s:%s:%s',
        v_congress,
        v_congress_year,
        v_roll_call_number
    );
    IF v_supplied_roll_call_key IS DISTINCT FROM v_roll_call_key THEN
        RAISE EXCEPTION
            'roll_call.source_record_key must equal the canonical House key %',
            v_roll_call_key
            USING ERRCODE = '22023';
    END IF;

    v_url_parts := regexp_match(
        v_source_url,
        '^https://clerk[.]house[.]gov/evs/([0-9]{4})/roll([0-9]+)[.]xml$'
    );
    IF v_url_parts IS NULL
       OR v_url_parts[1]::integer <> v_congress_year
       OR v_url_parts[2]::integer <> v_roll_call_number THEN
        RAISE EXCEPTION
            'roll_call.source_url must be the matching official House Clerk XML URL'
            USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0026_house_roll_call_provenance'
    ) THEN
        RAISE EXCEPTION 'House roll-call provenance migration marker is missing'
            USING ERRCODE = '55000';
    END IF;

    -- Lock the source and endpoint in the same order used by the enable/disable
    -- migration. A disable therefore either wins before this check or waits for
    -- this roll call to commit; ingestion can never commit after the disable.
    SELECT
        source.status,
        source.repo_fit,
        source.metadata ->> 'production_writes_enabled'
    INTO
        v_gate_source_status,
        v_gate_source_repo_fit,
        v_gate_source_writes_enabled
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'house-clerk-roll-call-xml'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'House roll-call source catalog row is missing'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        endpoint.status,
        endpoint.metadata ->> 'production_writes_enabled'
    INTO
        v_gate_endpoint_status,
        v_gate_endpoint_writes_enabled
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'house-clerk-roll-call-xml'
      AND endpoint.endpoint_slug = 'evs-roll-call-feed'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'House roll-call source catalog endpoint is missing'
            USING ERRCODE = '23503';
    END IF;

    IF v_gate_source_status IS DISTINCT FROM 'approved'
       OR v_gate_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_gate_endpoint_status IS DISTINCT FROM 'approved'
       OR v_gate_source_writes_enabled IS DISTINCT FROM 'true'
       OR v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION
            'authoritative House roll-call writes are disabled in the source catalog'
            USING ERRCODE = '55000';
    END IF;

    -- Serialize repeated ingestion of the same official event.
    PERFORM pg_advisory_xact_lock(hashtextextended(v_roll_call_key, 0));

    SELECT
        source.id,
        source.record_type,
        source.person_id,
        source.source_catalog_slug,
        source.source_endpoint_slug
    INTO
        v_roll_call_source_record_id,
        v_existing_record_type,
        v_existing_record_person_id,
        v_existing_catalog_slug,
        v_existing_endpoint_slug
    FROM public.source_records AS source
    WHERE source.source_system_key = 'house-clerk'
      AND source.source_record_key = v_roll_call_key
    FOR UPDATE;

    IF FOUND AND (
        v_existing_record_type IS DISTINCT FROM 'legislative_roll_call'
        OR v_existing_record_person_id IS NOT NULL
        OR v_existing_catalog_slug IS DISTINCT FROM 'house-clerk-roll-call-xml'
        OR v_existing_endpoint_slug IS DISTINCT FROM 'evs-roll-call-feed'
    ) THEN
        RAISE EXCEPTION
            'existing House roll-call source record conflicts with the reviewed provenance contract'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO public.source_records (
        source_system_key,
        source_record_key,
        record_type,
        person_id,
        source_catalog_slug,
        source_endpoint_slug,
        source_url,
        raw_payload_ref,
        payload_hash,
        verified_lane,
        record_status,
        first_seen_at,
        last_seen_at,
        metadata
    ) VALUES (
        'house-clerk',
        v_roll_call_key,
        'legislative_roll_call',
        NULL,
        'house-clerk-roll-call-xml',
        'evs-roll-call-feed',
        v_source_url,
        NULL,
        v_payload_hash,
        'verified',
        'active',
        v_fetched_at,
        v_fetched_at,
        jsonb_build_object(
            'ingestion_method', 'house_clerk_roll_call_xml',
            'raw_xml_retained', false,
            'chamber', 'house'
        )
    )
    ON CONFLICT (source_system_key, source_record_key) DO UPDATE SET
        source_url = EXCLUDED.source_url,
        raw_payload_ref = NULL,
        payload_hash = EXCLUDED.payload_hash,
        verified_lane = 'verified',
        record_status = 'active',
        retired_at = NULL,
        last_seen_at = GREATEST(
            public.source_records.last_seen_at,
            EXCLUDED.last_seen_at
        ),
        metadata = public.source_records.metadata || EXCLUDED.metadata
    RETURNING id INTO v_roll_call_source_record_id;

    SELECT
        roll_call.canonical_roll_call_key,
        roll_call.chamber,
        roll_call.congress,
        roll_call.session,
        roll_call.congress_year,
        roll_call.roll_call_number
    INTO
        v_existing_roll_call_key,
        v_existing_chamber,
        v_existing_congress,
        v_existing_session,
        v_existing_congress_year,
        v_existing_roll_call_number
    FROM public.legislative_roll_calls AS roll_call
    WHERE roll_call.source_record_id = v_roll_call_source_record_id
    FOR UPDATE;

    IF FOUND AND (
        v_existing_roll_call_key IS DISTINCT FROM v_roll_call_key
        OR v_existing_chamber IS DISTINCT FROM 'house'
        OR v_existing_congress IS DISTINCT FROM v_congress
        OR v_existing_session IS DISTINCT FROM v_session
        OR v_existing_congress_year IS DISTINCT FROM v_congress_year
        OR v_existing_roll_call_number IS DISTINCT FROM v_roll_call_number
    ) THEN
        RAISE EXCEPTION
            'existing normalized House roll call conflicts with its stable event identity'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO public.legislative_roll_calls (
        source_record_id,
        canonical_roll_call_key,
        chamber,
        congress,
        session,
        congress_year,
        roll_call_number,
        vote_date,
        question,
        vote_result,
        metadata
    ) VALUES (
        v_roll_call_source_record_id,
        v_roll_call_key,
        'house',
        v_congress,
        v_session,
        v_congress_year,
        v_roll_call_number,
        v_vote_date,
        v_question,
        v_vote_result,
        jsonb_build_object('source', 'house-clerk-roll-call-xml')
    )
    ON CONFLICT (source_record_id) DO UPDATE SET
        session = EXCLUDED.session,
        vote_date = EXCLUDED.vote_date,
        question = EXCLUDED.question,
        vote_result = EXCLUDED.vote_result,
        metadata = public.legislative_roll_calls.metadata || EXCLUDED.metadata;

    FOR v_member IN
        SELECT item.value
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        ORDER BY upper(btrim(item.value ->> 'bioguide_id'))
    LOOP
        v_bioguide_id := upper(btrim(v_member ->> 'bioguide_id'));
        IF v_bioguide_id !~ '^[A-Z][0-9]{6}$' THEN
            RAISE EXCEPTION 'invalid House Bioguide ID: %', v_bioguide_id
                USING ERRCODE = '22023';
        END IF;

        v_vote_cast := CASE lower(regexp_replace(
            btrim(v_member ->> 'vote_cast'),
            '[[:space:]_-]+',
            ' ',
            'g'
        ))
            WHEN 'aye' THEN 'yea'
            WHEN 'yes' THEN 'yea'
            WHEN 'yea' THEN 'yea'
            WHEN 'no' THEN 'nay'
            WHEN 'nay' THEN 'nay'
            WHEN 'present' THEN 'present'
            WHEN 'not voting' THEN 'not_voting'
            ELSE NULL
        END;
        IF v_vote_cast IS NULL THEN
            RAISE EXCEPTION
                'unsupported House vote cast for Bioguide ID %',
                v_bioguide_id
                USING ERRCODE = '22023';
        END IF;

        v_member_key := format('%s:%s', v_roll_call_key, v_bioguide_id);
        v_supplied_member_key := NULLIF(
            btrim(v_member ->> 'source_record_key'),
            ''
        );
        IF v_supplied_member_key IS DISTINCT FROM v_member_key THEN
            RAISE EXCEPTION
                'member source_record_key must equal the canonical House member key %',
                v_member_key
                USING ERRCODE = '22023';
        END IF;

        -- Lock every case-equivalent identity row and require exactly one owner.
        -- This accepts a historical mixed-case Bioguide value without making an
        -- ambiguous case-folded identity decision.
        PERFORM 1
        FROM public.person_external_ids AS external_id
        JOIN public.people AS person ON person.id = external_id.person_id
        WHERE external_id.source_system_key = 'bioguide'
          AND external_id.external_id_type = 'bioguide_id'
          AND upper(btrim(external_id.external_id)) = v_bioguide_id
        ORDER BY external_id.person_id
        FOR SHARE OF external_id, person;
        GET DIAGNOSTICS v_identity_match_count = ROW_COUNT;

        IF v_identity_match_count <> 1 THEN
            RAISE EXCEPTION
                'House member Bioguide ID % does not resolve to exactly one canonical identity row',
                v_bioguide_id
                USING ERRCODE = '23503';
        END IF;

        SELECT
            external_id.person_id,
            external_id.is_trusted,
            person.status
        INTO
            v_person_id,
            v_identity_is_trusted,
            v_person_status
        FROM public.person_external_ids AS external_id
        JOIN public.people AS person ON person.id = external_id.person_id
        WHERE external_id.source_system_key = 'bioguide'
          AND external_id.external_id_type = 'bioguide_id'
          AND upper(btrim(external_id.external_id)) = v_bioguide_id;

        IF NOT FOUND
           OR v_identity_is_trusted IS DISTINCT FROM true
           OR v_person_status IS DISTINCT FROM 'active' THEN
            RAISE EXCEPTION
                'House member Bioguide ID % does not resolve to one trusted active canonical person',
                v_bioguide_id
                USING ERRCODE = '23503';
        END IF;

        SELECT
            source.id,
            source.record_type,
            source.person_id,
            source.source_catalog_slug,
            source.source_endpoint_slug
        INTO
            v_member_source_record_id,
            v_existing_record_type,
            v_existing_record_person_id,
            v_existing_catalog_slug,
            v_existing_endpoint_slug
        FROM public.source_records AS source
        WHERE source.source_system_key = 'house-clerk'
          AND source.source_record_key = v_member_key
        FOR UPDATE;

        IF FOUND AND (
            v_existing_record_type IS DISTINCT FROM 'person_roll_call_vote'
            OR v_existing_record_person_id IS DISTINCT FROM v_person_id
            OR v_existing_catalog_slug IS DISTINCT FROM 'house-clerk-roll-call-xml'
            OR v_existing_endpoint_slug IS DISTINCT FROM 'evs-roll-call-feed'
        ) THEN
            RAISE EXCEPTION
                'existing House member-vote source record conflicts with its trusted identity'
                USING ERRCODE = '23505';
        END IF;

        INSERT INTO public.source_records (
            source_system_key,
            source_record_key,
            record_type,
            person_id,
            source_catalog_slug,
            source_endpoint_slug,
            source_url,
            raw_payload_ref,
            payload_hash,
            verified_lane,
            record_status,
            first_seen_at,
            last_seen_at,
            metadata
        ) VALUES (
            'house-clerk',
            v_member_key,
            'person_roll_call_vote',
            v_person_id,
            'house-clerk-roll-call-xml',
            'evs-roll-call-feed',
            v_source_url,
            NULL,
            v_payload_hash,
            'verified',
            'active',
            v_fetched_at,
            v_fetched_at,
            jsonb_build_object(
                'bioguide_id', v_bioguide_id,
                'ingestion_method', 'house_clerk_roll_call_xml',
                'raw_xml_retained', false
            )
        )
        ON CONFLICT (source_system_key, source_record_key) DO UPDATE SET
            source_url = EXCLUDED.source_url,
            raw_payload_ref = NULL,
            payload_hash = EXCLUDED.payload_hash,
            verified_lane = 'verified',
            record_status = 'active',
            retired_at = NULL,
            last_seen_at = GREATEST(
                public.source_records.last_seen_at,
                EXCLUDED.last_seen_at
            ),
            metadata = public.source_records.metadata || EXCLUDED.metadata
        RETURNING id INTO v_member_source_record_id;

        SELECT
            vote.source_record_id,
            vote.roll_call_source_record_id,
            vote.person_id,
            vote.vote_cast
        INTO
            v_existing_vote_source_record_id,
            v_existing_vote_roll_call_id,
            v_existing_vote_person_id,
            v_existing_vote_cast
        FROM public.person_roll_call_votes AS vote
        WHERE vote.source_record_id = v_member_source_record_id
           OR (
               vote.roll_call_source_record_id = v_roll_call_source_record_id
               AND vote.person_id = v_person_id
           )
        ORDER BY (vote.source_record_id = v_member_source_record_id) DESC
        LIMIT 1
        FOR UPDATE;

        IF FOUND AND (
            v_existing_vote_source_record_id IS DISTINCT FROM v_member_source_record_id
            OR v_existing_vote_roll_call_id IS DISTINCT FROM v_roll_call_source_record_id
            OR v_existing_vote_person_id IS DISTINCT FROM v_person_id
        ) THEN
            RAISE EXCEPTION
                'existing House member vote conflicts with its stable event or person identity'
                USING ERRCODE = '23505';
        END IF;

        IF FOUND AND v_existing_vote_cast IS DISTINCT FROM v_vote_cast THEN
            RAISE EXCEPTION
                'existing official House vote conflicts for roll call % and Bioguide ID %; preserving the last valid vote',
                v_roll_call_key,
                v_bioguide_id
                USING ERRCODE = '23505';
        END IF;

        INSERT INTO public.person_roll_call_votes (
            source_record_id,
            roll_call_source_record_id,
            person_id,
            vote_cast,
            metadata
        ) VALUES (
            v_member_source_record_id,
            v_roll_call_source_record_id,
            v_person_id,
            v_vote_cast,
            jsonb_build_object('bioguide_id', v_bioguide_id)
        )
        ON CONFLICT (source_record_id) DO UPDATE SET
            metadata = public.person_roll_call_votes.metadata || EXCLUDED.metadata;
    END LOOP;

    -- The input is one complete official roll-call snapshot. Retain omitted
    -- normalized facts for provenance, but retire their source records so future
    -- readers cannot mix a prior snapshot with the current one. Reappearance in a
    -- later complete snapshot reactivates the same stable source record.
    UPDATE public.source_records AS source
    SET
        record_status = 'retired',
        retired_at = GREATEST(source.last_seen_at, v_fetched_at),
        metadata = source.metadata || jsonb_build_object(
            'retirement_reason', 'omitted_from_complete_house_roll_call_snapshot',
            'retired_by_payload_hash', v_payload_hash
        )
    FROM public.person_roll_call_votes AS vote
    WHERE vote.source_record_id = source.id
      AND vote.roll_call_source_record_id = v_roll_call_source_record_id
      AND source.source_system_key = 'house-clerk'
      AND source.record_type = 'person_roll_call_vote'
      AND source.record_status = 'active'
      AND NOT (
          COALESCE(upper(btrim(source.metadata ->> 'bioguide_id')), '')
          = ANY(v_supplied_bioguide_ids)
      );

    RETURN QUERY SELECT v_roll_call_source_record_id, v_member_count;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.upsert_house_roll_call(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_house_roll_call(jsonb, jsonb)
    TO service_role;

UPDATE public.source_catalog_sources
SET metadata = metadata || jsonb_build_object(
    'ingestion_status', 'write_contract_ready_disabled',
    'production_write_status', 'disabled_pending_runtime_wiring',
    'production_writes_enabled', false,
    'provenance_tables', jsonb_build_array(
        'legislative_roll_calls',
        'person_roll_call_votes'
    ),
    'write_rpc', 'upsert_house_roll_call'
)
WHERE slug = 'house-clerk-roll-call-xml';

UPDATE public.source_catalog_endpoints
SET metadata = metadata || jsonb_build_object(
    'ingestion_status', 'write_contract_ready_disabled',
    'production_write_status', 'disabled_pending_runtime_wiring',
    'production_writes_enabled', false,
    'write_rpc', 'upsert_house_roll_call'
)
WHERE source_slug = 'house-clerk-roll-call-xml'
  AND endpoint_slug = 'evs-roll-call-feed';

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0026_house_roll_call_provenance',
    26,
    'Add private legislative roll-call provenance tables and an atomic, conflict-safe House write contract.',
    jsonb_build_object(
        'source_slug', 'house-clerk-roll-call-xml',
        'endpoint_slug', 'evs-roll-call-feed',
        'legislative_roll_calls', true,
        'person_roll_call_votes', true,
        'write_rpc', 'upsert_house_roll_call',
        'production_writes_enabled', false,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
