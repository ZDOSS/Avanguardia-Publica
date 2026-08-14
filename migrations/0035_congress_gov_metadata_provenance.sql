-- 0035_congress_gov_metadata_provenance.sql
--
-- Approve the bounded Congress.gov detail endpoint after three healthy
-- production-key observations, create private provenance-backed legislative
-- measure facts and exact official-roll-call links, and install one guarded
-- atomic batch writer. No raw JSON, person identity, legacy voting_records row,
-- or public read path is created. Runtime writes remain disabled by default and
-- scheduled writes remain disabled pending a manual canary and database audit.

BEGIN;

SET LOCAL statement_timeout = '60s';

DO $migration_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_ingestion_status text;
    v_source_writes_enabled text;
    v_endpoint_status text;
    v_endpoint_writes_enabled text;
    v_source_system_display_name text;
    v_source_system_kind text;
    v_source_system_trust_level text;
    v_source_system_verified boolean;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0035_congress_gov_metadata_provenance'
    ) THEN
        RAISE EXCEPTION
            'migration 0035_congress_gov_metadata_provenance is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0034_congress_gov_metadata_shadow_contract'
          AND migration_version = 34
    ) THEN
        RAISE EXCEPTION
            'migration 0034_congress_gov_metadata_shadow_contract must be applied first'
            USING ERRCODE = '55000';
    END IF;

    IF to_regclass('public.legislative_measures') IS NOT NULL
       OR to_regclass('public.legislative_roll_call_measure_links') IS NOT NULL THEN
        RAISE EXCEPTION
            'Congress.gov metadata tables already exist before migration 0035'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.source_records
        WHERE source_system_key = 'congress-gov'
           OR source_catalog_slug = 'congress-gov-api'
    ) THEN
        RAISE EXCEPTION
            'Congress.gov source-record namespace must be empty before migration 0035'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        source.status,
        source.repo_fit,
        source.metadata ->> 'ingestion_status',
        source.metadata ->> 'production_writes_enabled'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_ingestion_status,
        v_source_writes_enabled
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'congress-gov-api'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'required source catalog row is missing: congress-gov-api'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        endpoint.status,
        endpoint.metadata ->> 'production_writes_enabled'
    INTO
        v_endpoint_status,
        v_endpoint_writes_enabled
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'congress-gov-api'
      AND endpoint.endpoint_slug = 'api-v3'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: congress-gov-api.api-v3'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'candidate'
       OR v_source_repo_fit IS DISTINCT FROM 'needs_review'
       OR v_source_ingestion_status IS DISTINCT FROM 'shadow_only'
       OR v_source_writes_enabled IS DISTINCT FROM 'false'
       OR v_endpoint_status IS DISTINCT FROM 'candidate'
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'false' THEN
        RAISE EXCEPTION
            'Congress.gov provenance expected candidate/needs_review/shadow_only/disabled and candidate/disabled, found %/%/%/% and %/%',
            v_source_status,
            v_source_repo_fit,
            v_source_ingestion_status,
            v_source_writes_enabled,
            v_endpoint_status,
            v_endpoint_writes_enabled
            USING ERRCODE = '55000';
    END IF;

    SELECT display_name, source_kind, trust_level, verified
    INTO
        v_source_system_display_name,
        v_source_system_kind,
        v_source_system_trust_level,
        v_source_system_verified
    FROM public.source_systems
    WHERE key = 'congress-gov'
    FOR UPDATE;

    IF NOT FOUND
       OR v_source_system_display_name IS DISTINCT FROM 'Congress.gov API'
       OR v_source_system_kind IS DISTINCT FROM 'government'
       OR v_source_system_trust_level IS DISTINCT FROM 'official'
       OR v_source_system_verified IS DISTINCT FROM true THEN
        RAISE EXCEPTION
            'congress-gov source system does not match the reviewed official namespace'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_source_system_links
        WHERE source_slug = 'congress-gov-api'
          AND source_system_key = 'congress-gov'
          AND link_type = 'same_source'
    ) THEN
        RAISE EXCEPTION
            'Congress.gov catalog/source-system link is missing'
            USING ERRCODE = '23503';
    END IF;
END
$migration_preflight$;

-- Generic profile lifecycle RPCs also write source_records. Reserve the reviewed
-- Congress.gov measure keyspace so those paths cannot create person records or
-- retain raw payloads under this official namespace.
ALTER TABLE public.source_records
    ADD CONSTRAINT source_records_congress_gov_measure_contract
    CHECK ((
        NOT (
            (
                source_system_key = 'congress-gov'
                AND source_record_key ~
                    '^((bill:[1-9][0-9]*:(hr|s|hjres|sjres|hconres|sconres|hres|sres))|(amendment:[1-9][0-9]*:(hamdt|samdt|suamdt))):[1-9][0-9]*$'
            )
            OR source_catalog_slug IS NOT DISTINCT FROM 'congress-gov-api'
        )
        OR (
            source_system_key = 'congress-gov'
            AND record_type = 'legislative_measure'
            AND person_id IS NULL
            AND legacy_politician_id IS NULL
            AND source_catalog_slug = 'congress-gov-api'
            AND source_endpoint_slug = 'api-v3'
            AND source_url = 'https://api.congress.gov/v3/'
                || replace(source_record_key, ':', '/')
            AND raw_payload_ref IS NULL
            AND payload_hash ~ '^[0-9a-f]{64}$'
            AND verified_lane = 'verified'
            AND record_status = 'active'
            AND retired_at IS NULL
            AND (
                source_updated_at IS NULL
                OR source_updated_at <= last_seen_at + interval '5 minutes'
            )
            AND metadata ->> 'ingestion_method' =
                'congress_gov_api_v3_exact_detail'
            AND metadata -> 'raw_json_retained' = 'false'::jsonb
            AND metadata ->> 'measure_kind' = split_part(source_record_key, ':', 1)
        )
    ) IS TRUE)
    NOT VALID;

ALTER TABLE public.source_records
    VALIDATE CONSTRAINT source_records_congress_gov_measure_contract;

CREATE TABLE IF NOT EXISTS public.legislative_measures (
    source_record_id uuid PRIMARY KEY
        REFERENCES public.source_records(id) ON DELETE CASCADE,
    canonical_measure_key text NOT NULL UNIQUE,
    measure_kind text NOT NULL,
    congress integer NOT NULL,
    measure_type text NOT NULL,
    measure_number integer NOT NULL,
    title text,
    purpose text,
    description text,
    origin_chamber text,
    introduced_date date,
    update_date timestamptz,
    latest_action_date date,
    latest_action_text text,
    official_url text,
    amended_bill_source_record_key text,
    amended_amendment_source_record_key text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT legislative_measures_key_not_blank_check
        CHECK (NULLIF(btrim(canonical_measure_key), '') IS NOT NULL),
    CONSTRAINT legislative_measures_kind_check
        CHECK (measure_kind IN ('bill', 'amendment')),
    CONSTRAINT legislative_measures_identity_check
        CHECK (
            congress > 0
            AND measure_number > 0
            AND canonical_measure_key =
                measure_kind || ':' || congress::text || ':' ||
                measure_type || ':' || measure_number::text
            AND (
                (measure_kind = 'bill' AND measure_type IN (
                    'hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'
                ))
                OR
                (measure_kind = 'amendment' AND measure_type IN (
                    'hamdt', 'samdt', 'suamdt'
                ))
            )
        ),
    CONSTRAINT legislative_measures_chamber_check
        CHECK (origin_chamber IS NULL OR origin_chamber IN ('house', 'senate')),
    CONSTRAINT legislative_measures_amended_bill_key_check
        CHECK (
            amended_bill_source_record_key IS NULL
            OR amended_bill_source_record_key ~
                '^bill:[1-9][0-9]*:(hr|s|hjres|sjres|hconres|sconres|hres|sres):[1-9][0-9]*$'
        ),
    CONSTRAINT legislative_measures_amended_amendment_key_check
        CHECK (
            amended_amendment_source_record_key IS NULL
            OR amended_amendment_source_record_key ~
                '^amendment:[1-9][0-9]*:(hamdt|samdt|suamdt):[1-9][0-9]*$'
        )
);

CREATE TABLE IF NOT EXISTS public.legislative_roll_call_measure_links (
    roll_call_source_record_id uuid NOT NULL
        REFERENCES public.legislative_roll_calls(source_record_id) ON DELETE CASCADE,
    measure_source_record_id uuid NOT NULL
        REFERENCES public.legislative_measures(source_record_id) ON DELETE CASCADE,
    link_basis text NOT NULL DEFAULT 'exact_official_measure_identifier',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (roll_call_source_record_id, measure_source_record_id),
    CONSTRAINT legislative_roll_call_measure_links_basis_check
        CHECK (link_basis = 'exact_official_measure_identifier')
);

CREATE INDEX IF NOT EXISTS idx_legislative_measures_identity
    ON public.legislative_measures(
        congress,
        measure_kind,
        measure_type,
        measure_number
    );

CREATE INDEX IF NOT EXISTS idx_legislative_roll_call_measure_links_measure
    ON public.legislative_roll_call_measure_links(
        measure_source_record_id,
        roll_call_source_record_id
    );

CREATE TRIGGER legislative_measures_set_updated_at
    BEFORE UPDATE ON public.legislative_measures
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TRIGGER legislative_roll_call_measure_links_set_updated_at
    BEFORE UPDATE ON public.legislative_roll_call_measure_links
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.legislative_measures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.legislative_roll_call_measure_links ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.legislative_measures
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON TABLE public.legislative_roll_call_measure_links
    FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT ON TABLE public.legislative_measures TO service_role;
GRANT SELECT ON TABLE public.legislative_roll_call_measure_links TO service_role;

CREATE FUNCTION public.upsert_congress_gov_measure_metadata(
    p_measures jsonb,
    p_roll_call_links jsonb
)
RETURNS TABLE (
    measure_count integer,
    roll_call_link_count integer
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = ''
AS $function$
#variable_conflict use_column
DECLARE
    v_measure_count integer;
    v_link_count integer;
    v_item jsonb;
    v_text_field text;
    v_source_record_key text;
    v_kind text;
    v_congress integer;
    v_measure_type text;
    v_measure_number integer;
    v_title text;
    v_purpose text;
    v_description text;
    v_origin_chamber text;
    v_introduced_date date;
    v_update_date timestamptz;
    v_latest_action_date date;
    v_latest_action_text text;
    v_official_url text;
    v_amended_bill_key text;
    v_amended_amendment_key text;
    v_source_url text;
    v_payload_hash text;
    v_fetched_at timestamptz;
    v_expected_key text;
    v_expected_source_url text;
    v_presentation_slug text;
    v_expected_official_url text;
    v_source_record_id uuid;
    v_upserted_source_record_id uuid;
    v_existing_record_type text;
    v_existing_person_id uuid;
    v_existing_legacy_politician_id uuid;
    v_existing_catalog_slug text;
    v_existing_endpoint_slug text;
    v_existing_source_url text;
    v_existing_raw_payload_ref text;
    v_existing_payload_hash text;
    v_existing_verified_lane text;
    v_existing_record_status text;
    v_existing_last_seen_at timestamptz;
    v_source_record_exists boolean;
    v_existing_measure_source_record_id uuid;
    v_existing_measure_key text;
    v_existing_measure_kind text;
    v_existing_measure_congress integer;
    v_existing_measure_type text;
    v_existing_measure_number integer;
    v_measure_exists boolean;
    v_gate_source_status text;
    v_gate_source_repo_fit text;
    v_gate_source_writes_enabled text;
    v_gate_endpoint_status text;
    v_gate_endpoint_writes_enabled text;
    v_link_measure_key text;
    v_link_roll_call_key text;
    v_roll_call_source_system_key text;
    v_roll_call_catalog_slug text;
    v_roll_call_endpoint_slug text;
    v_roll_call_source_record_id uuid;
    v_roll_call_congress integer;
    v_measure_congress integer;
    v_link_measure_source_record_id uuid;
BEGIN
    -- Non-mutating schema-preflight probe.
    IF p_measures = '[{"preflight": true}]'::jsonb
       AND p_roll_call_links = '[]'::jsonb THEN
        RETURN QUERY SELECT 0::integer, 0::integer;
        RETURN;
    END IF;

    IF jsonb_typeof(p_measures) IS DISTINCT FROM 'array'
       OR jsonb_typeof(p_roll_call_links) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'measures and roll_call_links must be JSON arrays'
            USING ERRCODE = '22023';
    END IF;

    v_measure_count := jsonb_array_length(p_measures);
    v_link_count := jsonb_array_length(p_roll_call_links);
    IF v_measure_count < 1 OR v_measure_count > 100 THEN
        RAISE EXCEPTION 'measures must contain between 1 and 100 records'
            USING ERRCODE = '22023';
    END IF;
    IF v_link_count < 1 OR v_link_count > 5000 THEN
        RAISE EXCEPTION 'roll_call_links must contain between 1 and 5000 records'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_measures) AS item(value)
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'kind'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'measure_type'), '') IS NULL
           OR item.value -> 'congress' IS NULL
           OR item.value -> 'number' IS NULL
           OR NULLIF(btrim(item.value ->> 'source_url'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'payload_hash'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'fetched_at'), '') IS NULL
    ) THEN
        RAISE EXCEPTION 'every measure is missing one or more required fields'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_measures) AS item(value)
        CROSS JOIN LATERAL jsonb_object_keys(item.value) AS field_name(name)
        WHERE field_name.name NOT IN (
            'source_record_key',
            'kind',
            'congress',
            'measure_type',
            'number',
            'title',
            'purpose',
            'description',
            'origin_chamber',
            'introduced_date',
            'update_date',
            'latest_action_date',
            'latest_action_text',
            'official_url',
            'amended_bill_source_record_key',
            'amended_amendment_source_record_key',
            'source_url',
            'payload_hash',
            'fetched_at'
        )
    ) THEN
        RAISE EXCEPTION 'measure contains unsupported fields'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT btrim(item.value ->> 'source_record_key'))
        FROM jsonb_array_elements(p_measures) AS item(value)
    ) <> v_measure_count THEN
        RAISE EXCEPTION 'measures contains duplicate source_record_key values'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_roll_call_links) AS item(value)
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'measure_source_record_key'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'roll_call_source_record_key'), '') IS NULL
    ) THEN
        RAISE EXCEPTION 'every roll-call link must contain both exact source keys'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_roll_call_links) AS item(value)
        CROSS JOIN LATERAL jsonb_object_keys(item.value) AS field_name(name)
        WHERE field_name.name NOT IN (
            'measure_source_record_key',
            'roll_call_source_record_key'
        )
    ) THEN
        RAISE EXCEPTION 'roll-call link contains unsupported fields'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT (
            btrim(item.value ->> 'measure_source_record_key'),
            btrim(item.value ->> 'roll_call_source_record_key')
        ))
        FROM jsonb_array_elements(p_roll_call_links) AS item(value)
    ) <> v_link_count THEN
        RAISE EXCEPTION 'roll_call_links contains duplicate exact links'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_roll_call_links) AS link(value)
        WHERE NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_measures) AS measure(value)
            WHERE btrim(measure.value ->> 'source_record_key') =
                  btrim(link.value ->> 'measure_source_record_key')
        )
    ) OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_measures) AS measure(value)
        WHERE NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_roll_call_links) AS link(value)
            WHERE btrim(link.value ->> 'measure_source_record_key') =
                  btrim(measure.value ->> 'source_record_key')
        )
    ) THEN
        RAISE EXCEPTION 'measure facts and roll-call link measure keys differ'
            USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0035_congress_gov_metadata_provenance'
          AND migration_version = 35
    ) THEN
        RAISE EXCEPTION 'Congress.gov metadata provenance migration marker is missing'
            USING ERRCODE = '55000';
    END IF;

    -- Lock catalog gates before facts so a later disable cannot race this batch.
    SELECT
        source.status,
        source.repo_fit,
        source.metadata ->> 'production_writes_enabled'
    INTO
        v_gate_source_status,
        v_gate_source_repo_fit,
        v_gate_source_writes_enabled
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'congress-gov-api'
    FOR SHARE;

    SELECT
        endpoint.status,
        endpoint.metadata ->> 'production_writes_enabled'
    INTO
        v_gate_endpoint_status,
        v_gate_endpoint_writes_enabled
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'congress-gov-api'
      AND endpoint.endpoint_slug = 'api-v3'
    FOR SHARE;

    IF v_gate_source_status IS DISTINCT FROM 'approved'
       OR v_gate_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_gate_endpoint_status IS DISTINCT FROM 'approved'
       OR v_gate_source_writes_enabled IS DISTINCT FROM 'true'
       OR v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'Congress.gov metadata production writes are disabled'
            USING ERRCODE = '55000';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('congress-gov:measure-metadata-batch', 0)
    );

    FOR v_item IN
        SELECT item.value
        FROM jsonb_array_elements(p_measures) AS item(value)
        ORDER BY item.value ->> 'source_record_key'
    LOOP
        FOREACH v_text_field IN ARRAY ARRAY[
            'source_record_key',
            'kind',
            'measure_type',
            'title',
            'purpose',
            'description',
            'origin_chamber',
            'introduced_date',
            'update_date',
            'latest_action_date',
            'latest_action_text',
            'official_url',
            'amended_bill_source_record_key',
            'amended_amendment_source_record_key',
            'source_url',
            'payload_hash',
            'fetched_at'
        ]
        LOOP
            IF v_item ? v_text_field
               AND v_item -> v_text_field <> 'null'::jsonb
               AND jsonb_typeof(v_item -> v_text_field) IS DISTINCT FROM 'string' THEN
                RAISE EXCEPTION 'measure field % must be a string or null', v_text_field
                    USING ERRCODE = '22023';
            END IF;
        END LOOP;

        IF jsonb_typeof(v_item -> 'congress') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_item -> 'number') IS DISTINCT FROM 'number' THEN
            RAISE EXCEPTION 'measure congress and number must be JSON numbers'
                USING ERRCODE = '22023';
        END IF;

        BEGIN
            v_congress := (v_item ->> 'congress')::integer;
            v_measure_number := (v_item ->> 'number')::integer;
            v_introduced_date := NULLIF(
                btrim(v_item ->> 'introduced_date'),
                ''
            )::date;
            v_update_date := NULLIF(btrim(v_item ->> 'update_date'), '')::timestamptz;
            v_latest_action_date := NULLIF(
                btrim(v_item ->> 'latest_action_date'),
                ''
            )::date;
            v_fetched_at := NULLIF(btrim(v_item ->> 'fetched_at'), '')::timestamptz;
        EXCEPTION
            WHEN invalid_text_representation
                OR numeric_value_out_of_range
                OR datetime_field_overflow THEN
                RAISE EXCEPTION 'measure has an invalid integer, date, or timestamp field'
                    USING ERRCODE = '22023';
        END;

        v_source_record_key := NULLIF(btrim(v_item ->> 'source_record_key'), '');
        v_kind := lower(NULLIF(btrim(v_item ->> 'kind'), ''));
        v_measure_type := lower(NULLIF(btrim(v_item ->> 'measure_type'), ''));
        v_title := NULLIF(btrim(v_item ->> 'title'), '');
        v_purpose := NULLIF(btrim(v_item ->> 'purpose'), '');
        v_description := NULLIF(btrim(v_item ->> 'description'), '');
        v_origin_chamber := lower(NULLIF(btrim(v_item ->> 'origin_chamber'), ''));
        v_latest_action_text := NULLIF(btrim(v_item ->> 'latest_action_text'), '');
        v_official_url := NULLIF(btrim(v_item ->> 'official_url'), '');
        v_amended_bill_key := NULLIF(
            btrim(v_item ->> 'amended_bill_source_record_key'),
            ''
        );
        v_amended_amendment_key := NULLIF(
            btrim(v_item ->> 'amended_amendment_source_record_key'),
            ''
        );
        v_source_url := NULLIF(btrim(v_item ->> 'source_url'), '');
        v_payload_hash := lower(NULLIF(btrim(v_item ->> 'payload_hash'), ''));

        IF v_congress <= 0
           OR v_measure_number <= 0
           OR v_fetched_at IS NULL
           OR v_fetched_at > now() + interval '5 minutes'
           OR v_payload_hash !~ '^[0-9a-f]{64}$'
           OR v_origin_chamber NOT IN ('house', 'senate')
           OR char_length(COALESCE(v_title, '')) > 2000
           OR char_length(COALESCE(v_purpose, '')) > 20000
           OR char_length(COALESCE(v_description, '')) > 20000
           OR char_length(COALESCE(v_latest_action_text, '')) > 20000 THEN
            RAISE EXCEPTION 'measure contains an invalid bounded fact or provenance field'
                USING ERRCODE = '22023';
        END IF;

        IF (v_kind = 'bill' AND v_measure_type NOT IN (
                'hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'
            ))
           OR (v_kind = 'amendment' AND v_measure_type NOT IN (
                'hamdt', 'samdt', 'suamdt'
            ))
           OR v_kind NOT IN ('bill', 'amendment') THEN
            RAISE EXCEPTION 'measure kind and type do not form a supported identity'
                USING ERRCODE = '22023';
        END IF;

        v_expected_key := format(
            '%s:%s:%s:%s',
            v_kind,
            v_congress,
            v_measure_type,
            v_measure_number
        );
        v_expected_source_url := format(
            'https://api.congress.gov/v3/%s/%s/%s/%s',
            v_kind,
            v_congress,
            v_measure_type,
            v_measure_number
        );
        IF v_source_record_key IS DISTINCT FROM v_expected_key
           OR v_source_url IS DISTINCT FROM v_expected_source_url THEN
            RAISE EXCEPTION 'measure source key or API URL differs from its exact identity'
                USING ERRCODE = '22023';
        END IF;

        v_presentation_slug := CASE v_measure_type
            WHEN 'hr' THEN 'house-bill'
            WHEN 's' THEN 'senate-bill'
            WHEN 'hjres' THEN 'house-joint-resolution'
            WHEN 'sjres' THEN 'senate-joint-resolution'
            WHEN 'hconres' THEN 'house-concurrent-resolution'
            WHEN 'sconres' THEN 'senate-concurrent-resolution'
            WHEN 'hres' THEN 'house-resolution'
            WHEN 'sres' THEN 'senate-resolution'
            WHEN 'hamdt' THEN 'house-amendment'
            WHEN 'samdt' THEN 'senate-amendment'
            WHEN 'suamdt' THEN 'senate-amendment'
        END;
        v_expected_official_url := format(
            'https://www.congress.gov/%s/%sth-congress/%s/%s',
            v_kind,
            v_congress,
            v_presentation_slug,
            v_measure_number
        );
        IF v_official_url IS NOT NULL
           AND v_official_url IS DISTINCT FROM v_expected_official_url THEN
            RAISE EXCEPTION 'measure official URL differs from its exact identity'
                USING ERRCODE = '22023';
        END IF;

        IF v_amended_bill_key IS NOT NULL
           AND v_amended_bill_key !~
               '^bill:[1-9][0-9]*:(hr|s|hjres|sjres|hconres|sconres|hres|sres):[1-9][0-9]*$' THEN
            RAISE EXCEPTION 'measure contains an invalid amended bill identity'
                USING ERRCODE = '22023';
        END IF;
        IF v_amended_amendment_key IS NOT NULL
           AND v_amended_amendment_key !~
               '^amendment:[1-9][0-9]*:(hamdt|samdt|suamdt):[1-9][0-9]*$' THEN
            RAISE EXCEPTION 'measure contains an invalid amended amendment identity'
                USING ERRCODE = '22023';
        END IF;

        IF v_introduced_date > (v_fetched_at + interval '1 day')::date
           OR v_latest_action_date > (v_fetched_at + interval '1 day')::date
           OR v_update_date > v_fetched_at + interval '5 minutes' THEN
            RAISE EXCEPTION 'measure source dates occur after the observation window'
                USING ERRCODE = '22023';
        END IF;

        SELECT
            source.id,
            source.record_type,
            source.person_id,
            source.legacy_politician_id,
            source.source_catalog_slug,
            source.source_endpoint_slug,
            source.source_url,
            source.raw_payload_ref,
            source.payload_hash,
            source.verified_lane,
            source.record_status,
            source.last_seen_at
        INTO
            v_source_record_id,
            v_existing_record_type,
            v_existing_person_id,
            v_existing_legacy_politician_id,
            v_existing_catalog_slug,
            v_existing_endpoint_slug,
            v_existing_source_url,
            v_existing_raw_payload_ref,
            v_existing_payload_hash,
            v_existing_verified_lane,
            v_existing_record_status,
            v_existing_last_seen_at
        FROM public.source_records AS source
        WHERE source.source_system_key = 'congress-gov'
          AND source.source_record_key = v_source_record_key
        FOR UPDATE;
        v_source_record_exists := FOUND;

        IF v_source_record_exists AND (
            v_existing_record_type IS DISTINCT FROM 'legislative_measure'
            OR v_existing_person_id IS NOT NULL
            OR v_existing_legacy_politician_id IS NOT NULL
            OR v_existing_catalog_slug IS DISTINCT FROM 'congress-gov-api'
            OR v_existing_endpoint_slug IS DISTINCT FROM 'api-v3'
            OR v_existing_source_url IS DISTINCT FROM v_source_url
            OR v_existing_raw_payload_ref IS NOT NULL
            OR v_existing_payload_hash IS NULL
            OR v_existing_payload_hash !~ '^[0-9a-f]{64}$'
            OR v_existing_verified_lane IS DISTINCT FROM 'verified'
            OR v_existing_record_status IS DISTINCT FROM 'active'
        ) THEN
            RAISE EXCEPTION
                'existing Congress.gov source record conflicts with the reviewed provenance contract'
                USING ERRCODE = '23505';
        END IF;
        IF v_source_record_exists
           AND v_fetched_at < v_existing_last_seen_at
           AND v_payload_hash IS DISTINCT FROM v_existing_payload_hash THEN
            RAISE EXCEPTION 'stale Congress.gov observation conflicts with newer provenance'
                USING ERRCODE = '40001';
        END IF;
        IF v_source_record_exists
           AND v_fetched_at = v_existing_last_seen_at
           AND v_payload_hash IS DISTINCT FROM v_existing_payload_hash THEN
            RAISE EXCEPTION 'Congress.gov observation timestamp has conflicting payloads'
                USING ERRCODE = '23505';
        END IF;

        v_upserted_source_record_id := NULL;
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
            source_updated_at,
            first_seen_at,
            last_seen_at,
            metadata
        ) VALUES (
            'congress-gov',
            v_source_record_key,
            'legislative_measure',
            NULL,
            'congress-gov-api',
            'api-v3',
            v_source_url,
            NULL,
            v_payload_hash,
            'verified',
            'active',
            v_update_date,
            v_fetched_at,
            v_fetched_at,
            jsonb_build_object(
                'ingestion_method', 'congress_gov_api_v3_exact_detail',
                'raw_json_retained', false,
                'measure_kind', v_kind
            )
        )
        ON CONFLICT (source_system_key, source_record_key) DO UPDATE SET
            source_url = EXCLUDED.source_url,
            raw_payload_ref = NULL,
            payload_hash = CASE
                WHEN EXCLUDED.last_seen_at >= public.source_records.last_seen_at
                    THEN EXCLUDED.payload_hash
                ELSE public.source_records.payload_hash
            END,
            verified_lane = 'verified',
            record_status = 'active',
            source_updated_at = CASE
                WHEN EXCLUDED.last_seen_at >= public.source_records.last_seen_at
                    THEN COALESCE(
                        EXCLUDED.source_updated_at,
                        public.source_records.source_updated_at
                    )
                ELSE public.source_records.source_updated_at
            END,
            first_seen_at = LEAST(
                public.source_records.first_seen_at,
                EXCLUDED.first_seen_at
            ),
            last_seen_at = GREATEST(
                public.source_records.last_seen_at,
                EXCLUDED.last_seen_at
            ),
            retired_at = NULL,
            metadata = public.source_records.metadata || EXCLUDED.metadata
        WHERE EXCLUDED.last_seen_at > public.source_records.last_seen_at
        RETURNING id INTO v_upserted_source_record_id;

        IF v_upserted_source_record_id IS NOT NULL THEN
            v_source_record_id := v_upserted_source_record_id;
        ELSIF NOT v_source_record_exists THEN
            RAISE EXCEPTION 'Congress.gov source-record upsert returned no identity'
                USING ERRCODE = '55000';
        END IF;

        SELECT
            measure.source_record_id,
            measure.canonical_measure_key,
            measure.measure_kind,
            measure.congress,
            measure.measure_type,
            measure.measure_number
        INTO
            v_existing_measure_source_record_id,
            v_existing_measure_key,
            v_existing_measure_kind,
            v_existing_measure_congress,
            v_existing_measure_type,
            v_existing_measure_number
        FROM public.legislative_measures AS measure
        WHERE measure.source_record_id = v_source_record_id
        FOR UPDATE;
        v_measure_exists := FOUND;

        IF v_measure_exists AND (
            v_existing_measure_source_record_id IS DISTINCT FROM v_source_record_id
            OR v_existing_measure_key IS DISTINCT FROM v_source_record_key
            OR v_existing_measure_kind IS DISTINCT FROM v_kind
            OR v_existing_measure_congress IS DISTINCT FROM v_congress
            OR v_existing_measure_type IS DISTINCT FROM v_measure_type
            OR v_existing_measure_number IS DISTINCT FROM v_measure_number
        ) THEN
            RAISE EXCEPTION
                'existing normalized Congress.gov measure conflicts with its stable identity'
                USING ERRCODE = '23505';
        END IF;

        INSERT INTO public.legislative_measures (
            source_record_id,
            canonical_measure_key,
            measure_kind,
            congress,
            measure_type,
            measure_number,
            title,
            purpose,
            description,
            origin_chamber,
            introduced_date,
            update_date,
            latest_action_date,
            latest_action_text,
            official_url,
            amended_bill_source_record_key,
            amended_amendment_source_record_key,
            metadata
        ) VALUES (
            v_source_record_id,
            v_source_record_key,
            v_kind,
            v_congress,
            v_measure_type,
            v_measure_number,
            v_title,
            v_purpose,
            v_description,
            v_origin_chamber,
            v_introduced_date,
            v_update_date,
            v_latest_action_date,
            v_latest_action_text,
            v_official_url,
            v_amended_bill_key,
            v_amended_amendment_key,
            jsonb_build_object(
                'source', 'congress-gov-api',
                'raw_json_retained', false
            )
        )
        ON CONFLICT (source_record_id) DO UPDATE SET
            title = EXCLUDED.title,
            purpose = EXCLUDED.purpose,
            description = EXCLUDED.description,
            origin_chamber = EXCLUDED.origin_chamber,
            introduced_date = EXCLUDED.introduced_date,
            update_date = EXCLUDED.update_date,
            latest_action_date = EXCLUDED.latest_action_date,
            latest_action_text = EXCLUDED.latest_action_text,
            official_url = EXCLUDED.official_url,
            amended_bill_source_record_key = EXCLUDED.amended_bill_source_record_key,
            amended_amendment_source_record_key =
                EXCLUDED.amended_amendment_source_record_key,
            metadata = public.legislative_measures.metadata || EXCLUDED.metadata
        WHERE NOT v_source_record_exists
           OR v_fetched_at > v_existing_last_seen_at;
    END LOOP;

    FOR v_item IN
        SELECT item.value
        FROM jsonb_array_elements(p_roll_call_links) AS item(value)
        ORDER BY
            item.value ->> 'roll_call_source_record_key',
            item.value ->> 'measure_source_record_key'
    LOOP
        v_link_measure_key := NULLIF(
            btrim(v_item ->> 'measure_source_record_key'),
            ''
        );
        v_link_roll_call_key := NULLIF(
            btrim(v_item ->> 'roll_call_source_record_key'),
            ''
        );

        IF v_link_roll_call_key ~ '^house:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*$' THEN
            v_roll_call_source_system_key := 'house-clerk';
            v_roll_call_catalog_slug := 'house-clerk-roll-call-xml';
            v_roll_call_endpoint_slug := 'evs-roll-call-feed';
        ELSIF v_link_roll_call_key ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*$' THEN
            v_roll_call_source_system_key := 'senate-lis';
            v_roll_call_catalog_slug := 'senate-roll-call-xml';
            v_roll_call_endpoint_slug := 'lis-roll-call-feed';
        ELSE
            RAISE EXCEPTION 'roll-call link contains a noncanonical official key'
                USING ERRCODE = '22023';
        END IF;

        SELECT measure.source_record_id, measure.congress
        INTO v_link_measure_source_record_id, v_measure_congress
        FROM public.legislative_measures AS measure
        JOIN public.source_records AS source
          ON source.id = measure.source_record_id
        WHERE measure.canonical_measure_key = v_link_measure_key
          AND source.source_system_key = 'congress-gov'
          AND source.record_type = 'legislative_measure'
          AND source.source_catalog_slug = 'congress-gov-api'
          AND source.source_endpoint_slug = 'api-v3'
          AND source.verified_lane = 'verified'
          AND source.record_status = 'active';

        IF NOT FOUND THEN
            RAISE EXCEPTION 'roll-call link references an unavailable Congress.gov measure'
                USING ERRCODE = '23503';
        END IF;

        SELECT roll_call.source_record_id, roll_call.congress
        INTO v_roll_call_source_record_id, v_roll_call_congress
        FROM public.legislative_roll_calls AS roll_call
        JOIN public.source_records AS source
          ON source.id = roll_call.source_record_id
        WHERE source.source_system_key = v_roll_call_source_system_key
          AND source.source_record_key = v_link_roll_call_key
          AND source.record_type = 'legislative_roll_call'
          AND source.person_id IS NULL
          AND source.source_catalog_slug = v_roll_call_catalog_slug
          AND source.source_endpoint_slug = v_roll_call_endpoint_slug
          AND source.verified_lane = 'verified'
          AND source.record_status = 'active'
          AND roll_call.canonical_roll_call_key = v_link_roll_call_key;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'roll-call link references an unavailable official roll call'
                USING ERRCODE = '23503';
        END IF;
        IF v_roll_call_congress IS DISTINCT FROM v_measure_congress THEN
            RAISE EXCEPTION 'roll-call and measure Congress values differ'
                USING ERRCODE = '23503';
        END IF;

        INSERT INTO public.legislative_roll_call_measure_links (
            roll_call_source_record_id,
            measure_source_record_id,
            link_basis,
            metadata
        ) VALUES (
            v_roll_call_source_record_id,
            v_link_measure_source_record_id,
            'exact_official_measure_identifier',
            jsonb_build_object(
                'join_policy', 'exact_official_roll_call_measure_identifier_only',
                'roll_call_source_record_key', v_link_roll_call_key,
                'measure_source_record_key', v_link_measure_key
            )
        )
        ON CONFLICT (roll_call_source_record_id, measure_source_record_id)
        DO NOTHING;
    END LOOP;

    RETURN QUERY SELECT v_measure_count, v_link_count;
END
$function$;

REVOKE ALL ON FUNCTION public.upsert_congress_gov_measure_metadata(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.upsert_congress_gov_measure_metadata(jsonb, jsonb)
    TO service_role;

DO $catalog_approval$
DECLARE
    v_evidence jsonb := jsonb_build_object(
        'reviewed_at', '2026-08-13',
        'production_observation_run_ids', jsonb_build_array(
            31557812365,
            31663634544,
            31766400670
        ),
        'successful_observations', 3,
        'detail_requests_per_observation', 18,
        'successful_detail_responses_per_observation', 18,
        'identity_conflicts', 0,
        'source_failures', 0,
        'source_breakers', 0,
        'distinct_bill_references', 15,
        'distinct_amendment_references', 3,
        'exact_roll_call_measure_links_observed', 43,
        'raw_json_retained', false,
        'public_read_path_created', false,
        'runtime_default', 'disabled',
        'scheduled_runtime_writes_enabled', false
    );
BEGIN
    UPDATE public.source_catalog_sources
    SET
        status = 'approved',
        verified_lane = 'verified',
        repo_fit = 'wired',
        verified_at = DATE '2026-08-13',
        notes = 'Official Congress.gov API v3 approved for bounded exact-detail metadata retention in private provenance-backed tables. Collection crawling, raw JSON retention, public reads, and fuzzy joins remain prohibited.',
        metadata = metadata || jsonb_build_object(
            'repo_usage_status', 'Private provenance-backed bill/amendment metadata storage installed; runtime defaults disabled pending a manual write canary.',
            'repo_evidence', 'Three production-key observations each completed 18 of 18 exact detail requests with zero failures, identity conflicts, skips, or breakers.',
            'repo_next_action', 'Apply migration 0035, run one manual metadata-write canary, audit private facts and links, then review scheduled enablement separately.',
            'ingestion_status', 'private_provenance_storage',
            'source_review_status', 'approved',
            'production_writes_enabled', true,
            'production_observation', v_evidence
        )
    WHERE slug = 'congress-gov-api';

    UPDATE public.source_catalog_endpoints
    SET
        status = 'approved',
        notes = 'Approved only for bounded exact bill/amendment detail requests discovered in official roll-call XML. Private atomic writes are database-enabled; runtime and schedules remain disabled pending canary audit.',
        metadata = metadata || jsonb_build_object(
            'ingestion_status', 'private_provenance_storage',
            'collection_endpoints_allowed', false,
            'maximum_distinct_detail_requests_per_run', 100,
            'maximum_roll_call_links_per_run', 5000,
            'production_writes_enabled', true,
            'scheduled_runtime_writes_enabled', false,
            'production_observation', v_evidence
        )
    WHERE source_slug = 'congress-gov-api'
      AND endpoint_slug = 'api-v3';

    INSERT INTO public.source_catalog_review_events (
        source_slug,
        endpoint_slug,
        previous_status,
        new_status,
        reviewer,
        reason,
        evidence
    ) VALUES
        (
            'congress-gov-api',
            NULL,
            'candidate',
            'approved',
            'phase-4-congress-gov-provenance-review',
            'Approve bounded private normalized retention after three healthy exact-identity production observations.',
            v_evidence || jsonb_build_object('review_scope', 'source_private_storage')
        ),
        (
            'congress-gov-api',
            'api-v3',
            'candidate',
            'approved',
            'phase-4-congress-gov-provenance-review',
            'Approve only the existing bounded detail endpoints and exact roll-call link contract.',
            v_evidence || jsonb_build_object('review_scope', 'endpoint_private_storage')
        );

    INSERT INTO public.schema_migrations (
        migration_key,
        migration_version,
        description,
        metadata
    ) VALUES (
        '0035_congress_gov_metadata_provenance',
        35,
        'Create private Congress.gov measure provenance, exact official roll-call links, and a guarded atomic batch writer.',
        jsonb_build_object(
            'source_slug', 'congress-gov-api',
            'endpoint_slug', 'api-v3',
            'source_system_key', 'congress-gov',
            'source_status', 'approved',
            'repo_fit', 'wired',
            'production_writes_enabled', true,
            'runtime_default', 'disabled',
            'scheduled_runtime_writes_enabled', false,
            'scraper_preflight_required', true,
            'private_tables', jsonb_build_array(
                'legislative_measures',
                'legislative_roll_call_measure_links'
            ),
            'raw_json_retained', false,
            'public_read_path_created', false
        )
    );
END
$catalog_approval$;

NOTIFY pgrst, 'reload schema';

COMMIT;
