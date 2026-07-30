-- 0029_senate_roll_call_provenance.sql
--
-- Private, provenance-rich storage and an atomic write contract for official
-- U.S. Senate roll calls. The shared legislative fact tables already exist from
-- migration 0026; this migration reserves the canonical Senate keyspace and
-- installs a reviewed owner-only helper behind a hard public write barrier.
--
-- Production writes remain impossible after this migration. A separate reviewed
-- runtime/enablement migration must verify the helper contract, replace the public
-- barrier, and enable both strict JSON-boolean catalog gates.

BEGIN;

SET LOCAL statement_timeout = '30s';

DO $migration_preflight$
DECLARE
    v_source_status text;
    v_source_repo_fit text;
    v_source_ingestion_status text;
    v_source_write_status text;
    v_source_writes_enabled jsonb;
    v_endpoint_status text;
    v_endpoint_ingestion_status text;
    v_endpoint_write_status text;
    v_endpoint_writes_enabled jsonb;
    v_table_name text;
    v_column record;
    v_privilege text;
    v_protected_tables text[] := ARRAY[
        'public.source_records',
        'public.legislative_roll_calls',
        'public.person_roll_call_votes',
        'public.source_catalog_sources',
        'public.source_catalog_endpoints'
    ];
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0029_senate_roll_call_provenance'
    ) THEN
        RAISE EXCEPTION
            'migration 0029_senate_roll_call_provenance is already recorded; do not replay forward-only migrations'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0028_senate_roll_call_source_review'
    ) THEN
        RAISE EXCEPTION
            'migration 0028_senate_roll_call_source_review must be applied first'
            USING ERRCODE = '55000';
    END IF;

    SELECT
        status,
        repo_fit,
        metadata ->> 'ingestion_status',
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled'
    INTO
        v_source_status,
        v_source_repo_fit,
        v_source_ingestion_status,
        v_source_write_status,
        v_source_writes_enabled
    FROM public.source_catalog_sources
    WHERE slug = 'senate-roll-call-xml'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog row is missing: senate-roll-call-xml'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        status,
        metadata ->> 'ingestion_status',
        metadata ->> 'production_write_status',
        metadata -> 'production_writes_enabled'
    INTO
        v_endpoint_status,
        v_endpoint_ingestion_status,
        v_endpoint_write_status,
        v_endpoint_writes_enabled
    FROM public.source_catalog_endpoints
    WHERE source_slug = 'senate-roll-call-xml'
      AND endpoint_slug = 'lis-roll-call-feed'
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'required source catalog endpoint is missing: senate-roll-call-xml.lis-roll-call-feed'
            USING ERRCODE = '23503';
    END IF;

    IF v_source_status IS DISTINCT FROM 'approved'
       OR v_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_endpoint_status IS DISTINCT FROM 'approved'
       OR v_source_ingestion_status IS DISTINCT FROM 'shadow_only'
       OR v_endpoint_ingestion_status IS DISTINCT FROM 'shadow_only'
       OR v_source_write_status IS DISTINCT FROM 'disabled_pending_separate_ingestion_review'
       OR v_endpoint_write_status IS DISTINCT FROM 'disabled_pending_separate_ingestion_review'
       OR v_source_writes_enabled IS DISTINCT FROM 'false'::jsonb
       OR v_endpoint_writes_enabled IS DISTINCT FROM 'false'::jsonb THEN
        RAISE EXCEPTION
            'Senate provenance expected approved/wired/approved shadow-only rows with strict false write gates'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.source_systems
        WHERE key = 'senate-lis'
          AND display_name = 'U.S. Senate Legislative Information System'
          AND source_kind = 'government'
          AND trust_level = 'official'
          AND verified = true
    ) THEN
        RAISE EXCEPTION
            'reviewed senate-lis source system is missing or has drifted'
            USING ERRCODE = '55000';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_source_system_links
        WHERE source_slug = 'senate-roll-call-xml'
          AND source_system_key = 'senate-lis'
          AND link_type = 'same_source'
    ) OR NOT EXISTS (
        SELECT 1
        FROM public.source_catalog_source_system_links
        WHERE source_slug = 'senate-roll-call-xml'
          AND source_system_key = 'congress-legislators'
          AND link_type = 'identifier_source'
    ) THEN
        RAISE EXCEPTION
            'reviewed Senate source-system or identifier-source link is missing'
            USING ERRCODE = '55000';
    END IF;

    FOREACH v_table_name IN ARRAY ARRAY[
        'public.source_records',
        'public.legislative_roll_calls',
        'public.person_roll_call_votes',
        'public.person_external_ids',
        'public.people',
        'public.politicians',
        'public.legacy_profile_redirects'
    ] LOOP
        IF to_regclass(v_table_name) IS NULL THEN
            RAISE EXCEPTION 'required provenance table is missing: %', v_table_name
                USING ERRCODE = '42P01';
        END IF;
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS index_state
        WHERE index_state.indexrelid = to_regclass(
                'public.uq_person_external_ids_bioguide_normalized'
              )
          AND index_state.indrelid
                = 'public.person_external_ids'::regclass
          AND index_state.indisunique
          AND index_state.indisvalid
          AND index_state.indisready
          AND index_state.indnkeyatts = 3
          AND index_state.indkey[0] = (
                SELECT attribute.attnum
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid
                        = 'public.person_external_ids'::regclass
                  AND attribute.attname = 'source_system_key'
                  AND NOT attribute.attisdropped
          )
          AND index_state.indkey[1] = (
                SELECT attribute.attnum
                FROM pg_catalog.pg_attribute AS attribute
                WHERE attribute.attrelid
                        = 'public.person_external_ids'::regclass
                  AND attribute.attname = 'external_id_type'
                  AND NOT attribute.attisdropped
          )
          AND index_state.indkey[2] = 0
          AND pg_catalog.pg_get_expr(
                index_state.indexprs,
                index_state.indrelid
              ) = 'upper(btrim(external_id))'
          AND pg_catalog.pg_get_expr(
                index_state.indpred,
                index_state.indrelid
              ) = (
                '((source_system_key = ''bioguide''::text) AND '
                '(external_id_type = ''bioguide_id''::text))'
              )
    ) THEN
        RAISE EXCEPTION
            'case-normalized Bioguide ownership index is missing or has drifted'
            USING ERRCODE = '55000';
    END IF;

    IF to_regprocedure('public.upsert_senate_roll_call(jsonb,jsonb)') IS NOT NULL
       OR to_regprocedure('public.upsert_senate_roll_call_0029(jsonb,jsonb)') IS NOT NULL THEN
        RAISE EXCEPTION
            'an out-of-band Senate roll-call function already exists'
            USING ERRCODE = '55000';
    END IF;

    -- Migration 0027 closed direct service-role mutations on these shared
    -- provenance tables. Preserve that boundary for the Senate path.
    FOREACH v_table_name IN ARRAY v_protected_tables LOOP
        IF has_table_privilege('service_role', v_table_name, 'SELECT')
                IS DISTINCT FROM true THEN
            RAISE EXCEPTION
                'service-role SELECT privilege boundary has drifted for %',
                v_table_name
                USING ERRCODE = '42501';
        END IF;

        FOREACH v_privilege IN ARRAY ARRAY[
            'INSERT',
            'UPDATE',
            'DELETE',
            'TRUNCATE',
            'REFERENCES',
            'TRIGGER'
        ] LOOP
            IF has_table_privilege(
                'service_role',
                v_table_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service-role retains % privilege on %',
                    v_privilege,
                    v_table_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;

    FOR v_column IN
        SELECT
            format('%I.%I', columns.table_schema, columns.table_name)
                AS qualified_table_name,
            columns.column_name
        FROM information_schema.columns AS columns
        WHERE format('%I.%I', columns.table_schema, columns.table_name)
              = ANY(v_protected_tables)
        ORDER BY
            columns.table_schema,
            columns.table_name,
            columns.ordinal_position
    LOOP
        FOREACH v_privilege IN ARRAY ARRAY[
            'INSERT',
            'UPDATE',
            'REFERENCES'
        ] LOOP
            IF has_column_privilege(
                'service_role',
                v_column.qualified_table_name,
                v_column.column_name,
                v_privilege
            ) THEN
                RAISE EXCEPTION
                    'service-role retains column % privilege on %.%',
                    v_privilege,
                    v_column.qualified_table_name,
                    v_column.column_name
                    USING ERRCODE = '42501';
            END IF;
        END LOOP;
    END LOOP;
END
$migration_preflight$;

-- Block concurrent generic source-profile lifecycle writes while the new
-- namespace constraint is installed and its reviewed zero-fact baseline is
-- checked.
LOCK TABLE public.source_records,
    public.legislative_roll_calls,
    public.person_roll_call_votes
IN SHARE ROW EXCLUSIVE MODE;

DO $zero_fact_baseline$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.source_records
        WHERE source_system_key = 'senate-lis'
           OR source_catalog_slug = 'senate-roll-call-xml'
    ) OR EXISTS (
        SELECT 1
        FROM public.legislative_roll_calls
        WHERE chamber = 'senate'
           OR canonical_roll_call_key ~ '^senate:'
    ) THEN
        RAISE EXCEPTION
            'Senate provenance migration expected zero preexisting official Senate facts'
            USING ERRCODE = '55000';
    END IF;
END
$zero_fact_baseline$;

-- Reserve only the canonical Senate event/member-vote keyspace. Unrelated future
-- LIS record families remain available, while generic profile/retirement RPCs
-- cannot create malformed or partially-provenanced Senate vote records.
ALTER TABLE public.source_records
    ADD CONSTRAINT source_records_senate_roll_call_contract
    CHECK (
        NOT (
            (
                source_system_key = 'senate-lis'
                AND source_record_key
                    ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*(:.*)?$'
            )
            OR source_catalog_slug
                IS NOT DISTINCT FROM 'senate-roll-call-xml'
        )
        OR (
            source_system_key = 'senate-lis'
            AND legacy_politician_id IS NULL
            AND source_catalog_slug = 'senate-roll-call-xml'
            AND source_endpoint_slug = 'lis-roll-call-feed'
            AND source_url
                ~ '^https://www[.]senate[.]gov/legislative/LIS/roll_call_votes/vote[1-9][0-9]*[12]/vote_[1-9][0-9]*_[12]_[0-9]{5}[.]xml$'
            AND raw_payload_ref IS NULL
            AND payload_hash ~ '^[0-9a-f]{64}$'
            AND verified_lane = 'verified'
            AND source_updated_at IS NULL
            AND NOT (metadata ? 'last_profile_name')
            AND NOT (metadata ? 'retirement_rpc_at')
            AND (
                (
                    source_record_key
                        ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*$'
                    AND record_type = 'legislative_roll_call'
                    AND person_id IS NULL
                    AND record_status = 'active'
                    AND retired_at IS NULL
                    AND NOT (metadata ? 'retirement_reason')
                    AND NOT (metadata ? 'retired_by_payload_hash')
                    AND metadata ->> 'ingestion_method'
                        = 'senate_lis_roll_call_xml'
                    AND metadata -> 'raw_xml_retained' = 'false'::jsonb
                    AND metadata ->> 'chamber' = 'senate'
                    AND metadata ->> 'observation_fingerprint'
                        ~ '^[0-9a-f]{64}:[0-9a-f]{32}$'
                    AND metadata ->> 'normalized_snapshot_fingerprint'
                        ~ '^[0-9a-f]{32}$'
                    AND metadata ->> 'monotonic_guard_migration'
                        = '0029_senate_roll_call_provenance'
                )
                OR (
                    source_record_key
                        ~ '^senate:[1-9][0-9]*:[0-9]{4}:[1-9][0-9]*:S[0-9]{3}$'
                    AND record_type = 'person_roll_call_vote'
                    AND person_id IS NOT NULL
                    AND upper(btrim(metadata ->> 'lis_member_id'))
                        = substring(source_record_key FROM '(S[0-9]{3})$')
                    AND upper(btrim(metadata ->> 'bioguide_id'))
                        ~ '^[A-Z][0-9]{6}$'
                    AND metadata ->> 'identity_crosswalk_source_system'
                        = 'congress-legislators'
                    AND metadata ->> 'identity_crosswalk_source_record_id'
                        ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                    AND metadata ->> 'ingestion_method'
                        = 'senate_lis_roll_call_xml'
                    AND metadata -> 'raw_xml_retained' = 'false'::jsonb
                    AND (
                        (
                            record_status = 'active'
                            AND retired_at IS NULL
                            AND NOT (metadata ? 'retirement_reason')
                            AND NOT (metadata ? 'retired_by_payload_hash')
                        )
                        OR (
                            record_status = 'retired'
                            AND retired_at IS NOT NULL
                            AND metadata ->> 'retirement_reason'
                                = 'omitted_from_complete_senate_roll_call_snapshot'
                            AND metadata ->> 'retired_by_payload_hash'
                                ~ '^[0-9a-f]{64}$'
                        )
                    )
                )
            )
        ) IS TRUE
    )
    NOT VALID;

ALTER TABLE public.source_records
    VALIDATE CONSTRAINT source_records_senate_roll_call_contract;

-- Owner-only implementation of one complete, monotonic Senate roll-call
-- observation. The public service-role function installed below is a hard
-- barrier and cannot call this helper until a later reviewed enablement.
CREATE FUNCTION public.upsert_senate_roll_call_0029(
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
    v_fetched_at timestamptz;
    v_payload_hash text;
    v_source_url text;
    v_url_parts text[];
    v_supplied_roll_call_key text;
    v_roll_call_key text;
    v_member_count integer;
    v_supplied_lis_ids text[];
    v_observation_fingerprint text;
    v_normalized_snapshot_fingerprint text;
    v_actual_snapshot_fingerprint text;
    v_actual_active_member_count integer;
    v_gate_source_status text;
    v_gate_source_repo_fit text;
    v_gate_source_writes_enabled jsonb;
    v_gate_endpoint_status text;
    v_gate_endpoint_writes_enabled jsonb;
    v_existing_roll_call_source_record_id uuid;
    v_existing_record_type text;
    v_existing_record_person_id uuid;
    v_existing_catalog_slug text;
    v_existing_endpoint_slug text;
    v_existing_source_url text;
    v_existing_raw_payload_ref text;
    v_existing_payload_hash text;
    v_existing_verified_lane text;
    v_existing_record_status text;
    v_existing_last_seen_at timestamptz;
    v_existing_retired_at timestamptz;
    v_existing_metadata jsonb;
    v_existing_roll_call_key text;
    v_existing_chamber text;
    v_existing_congress integer;
    v_existing_session smallint;
    v_existing_congress_year integer;
    v_existing_roll_call_number integer;
    v_existing_vote_date date;
    v_existing_question text;
    v_existing_vote_result text;
    v_existing_roll_call_metadata jsonb;
    v_member jsonb;
    v_lis_member_id text;
    v_bioguide_id text;
    v_vote_cast text;
    v_member_key text;
    v_person_id uuid;
    v_crosswalk_source_record_id uuid;
    v_member_source_record_id uuid;
    v_member_source_preexisting boolean;
    v_existing_vote_source_record_id uuid;
    v_existing_vote_roll_call_id uuid;
    v_existing_vote_person_id uuid;
    v_existing_vote_cast text;
    v_existing_vote_metadata jsonb;
    v_existing_member_raw_payload_ref text;
    v_existing_member_verified_lane text;
    v_existing_member_metadata jsonb;
BEGIN
    IF jsonb_typeof(p_roll_call) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'roll_call must be a JSON object' USING ERRCODE = '22023';
    END IF;

    IF jsonb_typeof(p_member_votes) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'member_votes must be a JSON array' USING ERRCODE = '22023';
    END IF;

    v_member_count := jsonb_array_length(p_member_votes);
    IF v_member_count = 0 OR v_member_count > 200 THEN
        RAISE EXCEPTION 'member_votes must contain between 1 and 200 votes'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE jsonb_typeof(item.value) IS DISTINCT FROM 'object'
           OR NULLIF(btrim(item.value ->> 'lis_member_id'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'bioguide_id'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'vote_cast'), '') IS NULL
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '') IS NULL
    ) THEN
        RAISE EXCEPTION
            'every member vote must contain lis_member_id, bioguide_id, vote_cast, and source_record_key'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT upper(btrim(item.value ->> 'lis_member_id')))
        FROM jsonb_array_elements(p_member_votes) AS item(value)
    ) <> v_member_count THEN
        RAISE EXCEPTION 'member_votes contains duplicate LIS member IDs'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(DISTINCT upper(btrim(item.value ->> 'bioguide_id')))
        FROM jsonb_array_elements(p_member_votes) AS item(value)
    ) <> v_member_count THEN
        RAISE EXCEPTION 'member_votes contains duplicate Bioguide IDs'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_congress := NULLIF(btrim(p_roll_call ->> 'congress'), '')::integer;
        v_session := NULLIF(btrim(p_roll_call ->> 'session'), '')::smallint;
        v_congress_year := NULLIF(btrim(p_roll_call ->> 'congress_year'), '')::integer;
        v_roll_call_number := NULLIF(btrim(p_roll_call ->> 'roll_call_number'), '')::integer;
        v_vote_date := NULLIF(btrim(p_roll_call ->> 'vote_date'), '')::date;
        v_fetched_at := NULLIF(btrim(p_roll_call ->> 'fetched_at'), '')::timestamptz;
    EXCEPTION
        WHEN invalid_text_representation OR datetime_field_overflow THEN
            RAISE EXCEPTION 'roll_call has an invalid identity, date, or timestamp field'
                USING ERRCODE = '22023';
    END;

    v_supplied_roll_call_key := NULLIF(
        btrim(p_roll_call ->> 'source_record_key'),
        ''
    );
    v_payload_hash := lower(NULLIF(btrim(p_roll_call ->> 'payload_hash'), ''));
    v_source_url := NULLIF(btrim(p_roll_call ->> 'source_url'), '');
    v_question := NULLIF(btrim(p_roll_call ->> 'question'), '');
    v_vote_result := NULLIF(btrim(p_roll_call ->> 'vote_result'), '');

    IF v_congress IS NULL
       OR v_congress <= 0
       OR v_session IS NULL
       OR v_session NOT IN (1, 2)
       OR v_congress_year IS NULL
       OR v_congress_year NOT BETWEEN 1789 AND 2200
       OR v_roll_call_number IS NULL
       OR v_roll_call_number <= 0
       OR v_vote_date IS NULL
       OR EXTRACT(YEAR FROM v_vote_date)::integer <> v_congress_year
       OR v_question IS NULL
       OR v_fetched_at IS NULL
       OR v_payload_hash IS NULL
       OR v_source_url IS NULL THEN
        RAISE EXCEPTION 'roll_call is missing a required monotonic-observation field'
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
        'senate:%s:%s:%s',
        v_congress,
        v_congress_year,
        v_roll_call_number
    );
    IF v_supplied_roll_call_key IS DISTINCT FROM v_roll_call_key THEN
        RAISE EXCEPTION
            'roll_call.source_record_key must equal the canonical Senate key %',
            v_roll_call_key
            USING ERRCODE = '22023';
    END IF;

    v_url_parts := regexp_match(
        v_source_url,
        '^https://www[.]senate[.]gov/legislative/LIS/roll_call_votes/vote([1-9][0-9]*)([12])/vote_([1-9][0-9]*)_([12])_([0-9]{5})[.]xml$'
    );
    IF v_url_parts IS NULL
       OR v_url_parts[1]::integer <> v_congress
       OR v_url_parts[2]::smallint <> v_session
       OR v_url_parts[3]::integer <> v_congress
       OR v_url_parts[4]::smallint <> v_session
       OR v_url_parts[5]::integer <> v_roll_call_number THEN
        RAISE EXCEPTION
            'roll_call.source_url must be the matching official Senate LIS XML URL'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE upper(btrim(item.value ->> 'lis_member_id')) !~ '^S[0-9]{3}$'
           OR upper(btrim(item.value ->> 'bioguide_id')) !~ '^[A-Z][0-9]{6}$'
           OR NULLIF(btrim(item.value ->> 'source_record_key'), '')
                IS DISTINCT FROM format(
                    '%s:%s',
                    v_roll_call_key,
                    upper(btrim(item.value ->> 'lis_member_id'))
                )
           OR CASE lower(regexp_replace(
                btrim(item.value ->> 'vote_cast'),
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
           END IS NULL
    ) THEN
        RAISE EXCEPTION 'member_votes contains an invalid ID, key, or vote cast'
            USING ERRCODE = '22023';
    END IF;

    SELECT array_agg(
        upper(btrim(item.value ->> 'lis_member_id'))
        ORDER BY upper(btrim(item.value ->> 'lis_member_id'))
    )
    INTO v_supplied_lis_ids
    FROM jsonb_array_elements(p_member_votes) AS item(value);

    v_observation_fingerprint := concat(
        v_payload_hash,
        ':',
        md5(p_roll_call::text || E'\n' || p_member_votes::text)
    );

    IF NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE migration_key = '0029_senate_roll_call_provenance'
    ) THEN
        RAISE EXCEPTION 'Senate roll-call provenance migration marker is missing'
            USING ERRCODE = '55000';
    END IF;

    -- A future enablement wrapper and this helper must use this exact lock order.
    SELECT
        source.status,
        source.repo_fit,
        source.metadata -> 'production_writes_enabled'
    INTO
        v_gate_source_status,
        v_gate_source_repo_fit,
        v_gate_source_writes_enabled
    FROM public.source_catalog_sources AS source
    WHERE source.slug = 'senate-roll-call-xml'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Senate roll-call source catalog row is missing'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        endpoint.status,
        endpoint.metadata -> 'production_writes_enabled'
    INTO
        v_gate_endpoint_status,
        v_gate_endpoint_writes_enabled
    FROM public.source_catalog_endpoints AS endpoint
    WHERE endpoint.source_slug = 'senate-roll-call-xml'
      AND endpoint.endpoint_slug = 'lis-roll-call-feed'
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Senate roll-call source catalog endpoint is missing'
            USING ERRCODE = '23503';
    END IF;

    IF v_gate_source_status IS DISTINCT FROM 'approved'
       OR v_gate_source_repo_fit IS DISTINCT FROM 'wired'
       OR v_gate_endpoint_status IS DISTINCT FROM 'approved'
       OR v_gate_source_writes_enabled IS DISTINCT FROM 'true'::jsonb
       OR v_gate_endpoint_writes_enabled IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION
            'authoritative Senate roll-call writes are disabled in the source catalog'
            USING ERRCODE = '55000';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_roll_call_key, 0)
    );

    -- Lock all case-equivalent Bioguide owners before validating the complete
    -- incoming crosswalk. Names, party, state, and office text never participate.
    PERFORM 1
    FROM public.person_external_ids AS external_id
    JOIN public.people AS person ON person.id = external_id.person_id
    WHERE external_id.source_system_key = 'bioguide'
      AND external_id.external_id_type = 'bioguide_id'
      AND upper(btrim(external_id.external_id)) IN (
          SELECT upper(btrim(item.value ->> 'bioguide_id'))
          FROM jsonb_array_elements(p_member_votes) AS item(value)
      )
    ORDER BY external_id.person_id
    FOR SHARE OF external_id, person;

    -- Independently lock the exact congress-legislators profile records and their
    -- source-native legacy rows. This proves each caller-supplied LIS/Bioguide pair
    -- came from stored trusted roster provenance before any vote fact can be written.
    PERFORM 1
    FROM jsonb_array_elements(p_member_votes) AS item(value)
    JOIN public.person_external_ids AS external_id
      ON external_id.source_system_key = 'bioguide'
     AND external_id.external_id_type = 'bioguide_id'
     AND upper(btrim(external_id.external_id))
            = upper(btrim(item.value ->> 'bioguide_id'))
    JOIN public.people AS person ON person.id = external_id.person_id
    JOIN public.source_records AS crosswalk_source
      ON crosswalk_source.source_system_key = 'congress-legislators'
     AND crosswalk_source.source_record_key
            = upper(btrim(item.value ->> 'bioguide_id'))
     AND crosswalk_source.person_id = external_id.person_id
    JOIN public.politicians AS profile
      ON profile.id = crosswalk_source.legacy_politician_id
     AND upper(btrim(profile.bioguide_id))
            = upper(btrim(item.value ->> 'bioguide_id'))
     AND upper(btrim(profile.external_ids ->> 'lis'))
            = upper(btrim(item.value ->> 'lis_member_id'))
    JOIN public.legacy_profile_redirects AS redirect
      ON redirect.legacy_politician_id = profile.id
     AND redirect.person_id = external_id.person_id
    ORDER BY crosswalk_source.id
    FOR SHARE OF external_id, person, crosswalk_source, profile, redirect;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_member_votes) AS item(value)
        WHERE (
            SELECT count(*)
            FROM public.person_external_ids AS external_id
            JOIN public.people AS person ON person.id = external_id.person_id
            WHERE external_id.source_system_key = 'bioguide'
              AND external_id.external_id_type = 'bioguide_id'
              AND upper(btrim(external_id.external_id))
                    = upper(btrim(item.value ->> 'bioguide_id'))
        ) <> 1
           OR NOT EXISTS (
                SELECT 1
                FROM public.person_external_ids AS external_id
                JOIN public.people AS person ON person.id = external_id.person_id
                JOIN public.source_records AS crosswalk_source
                  ON crosswalk_source.source_system_key = 'congress-legislators'
                 AND crosswalk_source.source_record_key
                        = upper(btrim(item.value ->> 'bioguide_id'))
                 AND crosswalk_source.person_id = external_id.person_id
                 AND crosswalk_source.record_type = 'person_profile'
                 AND crosswalk_source.record_status IN ('active', 'retired')
                 AND crosswalk_source.source_catalog_slug = 'congress-legislators'
                 AND crosswalk_source.source_endpoint_slug = 'repository'
                JOIN public.politicians AS profile
                  ON profile.id = crosswalk_source.legacy_politician_id
                 AND upper(btrim(profile.bioguide_id))
                        = upper(btrim(item.value ->> 'bioguide_id'))
                 AND upper(btrim(profile.external_ids ->> 'lis'))
                        = upper(btrim(item.value ->> 'lis_member_id'))
                JOIN public.legacy_profile_redirects AS redirect
                  ON redirect.legacy_politician_id = profile.id
                 AND redirect.person_id = external_id.person_id
                WHERE external_id.source_system_key = 'bioguide'
                  AND external_id.external_id_type = 'bioguide_id'
                  AND upper(btrim(external_id.external_id))
                        = upper(btrim(item.value ->> 'bioguide_id'))
                  AND external_id.is_trusted = true
                  AND person.status = 'active'
           )
    ) THEN
        RAISE EXCEPTION
            'every Senate LIS/Bioguide pair must resolve through one stored trusted congress-legislators profile'
            USING ERRCODE = '23503';
    END IF;

    -- Hash the fully normalized, identity-resolved input. A same-timestamp retry
    -- later compares this against both stored metadata and the complete active
    -- child state before returning without firing update triggers.
    SELECT md5(COALESCE(jsonb_agg(
        jsonb_build_object(
            'source_record_key',
                btrim(item.value ->> 'source_record_key'),
            'lis_member_id',
                upper(btrim(item.value ->> 'lis_member_id')),
            'bioguide_id',
                upper(btrim(item.value ->> 'bioguide_id')),
            'person_id',
                external_id.person_id,
            'identity_crosswalk_source_record_id',
                crosswalk_source.id,
            'vote_cast',
                CASE lower(regexp_replace(
                    btrim(item.value ->> 'vote_cast'),
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
                END,
            'source_system_key', 'senate-lis',
            'record_type', 'person_roll_call_vote',
            'source_catalog_slug', 'senate-roll-call-xml',
            'source_endpoint_slug', 'lis-roll-call-feed',
            'source_url', v_source_url,
            'raw_payload_ref', NULL,
            'payload_hash', v_payload_hash,
            'verified_lane', 'verified',
            'record_status', 'active',
            'retired_at', NULL,
            'last_seen_at', v_fetched_at,
            'member_ingestion_method', 'senate_lis_roll_call_xml',
            'member_raw_xml_retained', false,
            'identity_crosswalk_source_system', 'congress-legislators',
            'vote_metadata_lis_member_id',
                upper(btrim(item.value ->> 'lis_member_id')),
            'vote_metadata_bioguide_id',
                upper(btrim(item.value ->> 'bioguide_id')),
            'vote_source_matches', true,
            'vote_roll_call_matches', true,
            'vote_person_matches', true
        )
        ORDER BY upper(btrim(item.value ->> 'lis_member_id'))
    )::text, '[]'))
    INTO v_normalized_snapshot_fingerprint
    FROM jsonb_array_elements(p_member_votes) AS item(value)
    JOIN public.person_external_ids AS external_id
      ON external_id.source_system_key = 'bioguide'
     AND external_id.external_id_type = 'bioguide_id'
     AND upper(btrim(external_id.external_id))
            = upper(btrim(item.value ->> 'bioguide_id'))
     AND external_id.is_trusted = true
    JOIN public.people AS person
      ON person.id = external_id.person_id
     AND person.status = 'active'
    JOIN public.source_records AS crosswalk_source
      ON crosswalk_source.source_system_key = 'congress-legislators'
     AND crosswalk_source.source_record_key
            = upper(btrim(item.value ->> 'bioguide_id'))
     AND crosswalk_source.person_id = external_id.person_id
     AND crosswalk_source.record_type = 'person_profile'
     AND crosswalk_source.record_status IN ('active', 'retired')
     AND crosswalk_source.source_catalog_slug = 'congress-legislators'
     AND crosswalk_source.source_endpoint_slug = 'repository'
    JOIN public.politicians AS profile
      ON profile.id = crosswalk_source.legacy_politician_id
     AND upper(btrim(profile.bioguide_id))
            = upper(btrim(item.value ->> 'bioguide_id'))
     AND upper(btrim(profile.external_ids ->> 'lis'))
            = upper(btrim(item.value ->> 'lis_member_id'))
    JOIN public.legacy_profile_redirects AS redirect
      ON redirect.legacy_politician_id = profile.id
     AND redirect.person_id = external_id.person_id;

    SELECT
        source.id,
        source.record_type,
        source.person_id,
        source.source_catalog_slug,
        source.source_endpoint_slug,
        source.source_url,
        source.raw_payload_ref,
        source.payload_hash,
        source.verified_lane,
        source.record_status,
        source.last_seen_at,
        source.retired_at,
        source.metadata
    INTO
        v_existing_roll_call_source_record_id,
        v_existing_record_type,
        v_existing_record_person_id,
        v_existing_catalog_slug,
        v_existing_endpoint_slug,
        v_existing_source_url,
        v_existing_raw_payload_ref,
        v_existing_payload_hash,
        v_existing_verified_lane,
        v_existing_record_status,
        v_existing_last_seen_at,
        v_existing_retired_at,
        v_existing_metadata
    FROM public.source_records AS source
    WHERE source.source_system_key = 'senate-lis'
      AND source.source_record_key = v_roll_call_key
    FOR UPDATE;

    IF FOUND THEN
        IF v_existing_record_type IS DISTINCT FROM 'legislative_roll_call'
           OR v_existing_record_person_id IS NOT NULL
           OR v_existing_catalog_slug IS DISTINCT FROM 'senate-roll-call-xml'
           OR v_existing_endpoint_slug IS DISTINCT FROM 'lis-roll-call-feed'
           OR v_existing_raw_payload_ref IS NOT NULL
           OR v_existing_verified_lane IS DISTINCT FROM 'verified'
           OR v_existing_record_status IS DISTINCT FROM 'active'
           OR v_existing_last_seen_at IS NULL
           OR v_existing_retired_at IS NOT NULL THEN
            RAISE EXCEPTION
                'existing Senate roll-call source record conflicts with the production provenance contract'
                USING ERRCODE = '23505';
        END IF;

        SELECT
            roll_call.canonical_roll_call_key,
            roll_call.chamber,
            roll_call.congress,
            roll_call.session,
            roll_call.congress_year,
            roll_call.roll_call_number,
            roll_call.vote_date,
            roll_call.question,
            roll_call.vote_result,
            roll_call.metadata
        INTO
            v_existing_roll_call_key,
            v_existing_chamber,
            v_existing_congress,
            v_existing_session,
            v_existing_congress_year,
            v_existing_roll_call_number,
            v_existing_vote_date,
            v_existing_question,
            v_existing_vote_result,
            v_existing_roll_call_metadata
        FROM public.legislative_roll_calls AS roll_call
        WHERE roll_call.source_record_id = v_existing_roll_call_source_record_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'existing Senate roll-call source record is missing its normalized fact'
                USING ERRCODE = '23503';
        END IF;

        IF v_existing_roll_call_key IS DISTINCT FROM v_roll_call_key
           OR v_existing_chamber IS DISTINCT FROM 'senate'
           OR v_existing_congress IS DISTINCT FROM v_congress
           OR v_existing_session IS DISTINCT FROM v_session
           OR v_existing_congress_year IS DISTINCT FROM v_congress_year
           OR v_existing_roll_call_number IS DISTINCT FROM v_roll_call_number THEN
            RAISE EXCEPTION
                'existing normalized Senate roll call conflicts with its stable event identity'
                USING ERRCODE = '23505';
        END IF;

        IF v_fetched_at < v_existing_last_seen_at THEN
            RAISE EXCEPTION
                'stale Senate roll-call observation for %: fetched_at % precedes stored %',
                v_roll_call_key,
                v_fetched_at,
                v_existing_last_seen_at
                USING ERRCODE = '55000';
        END IF;

        IF v_fetched_at = v_existing_last_seen_at THEN
            IF v_existing_payload_hash IS DISTINCT FROM v_payload_hash
               OR v_existing_source_url IS DISTINCT FROM v_source_url
               OR (v_existing_metadata ->> 'ingestion_method')
                    IS DISTINCT FROM 'senate_lis_roll_call_xml'
               OR (v_existing_metadata -> 'raw_xml_retained')
                    IS DISTINCT FROM 'false'::jsonb
               OR (v_existing_metadata ->> 'chamber') IS DISTINCT FROM 'senate'
               OR (v_existing_metadata ->> 'observation_fingerprint')
                    IS DISTINCT FROM v_observation_fingerprint
               OR (v_existing_metadata ->> 'observation_fingerprint_version')
                    IS DISTINCT FROM 'payload_sha256_plus_jsonb_args_md5_v1'
               OR (v_existing_metadata ->> 'normalized_snapshot_fingerprint')
                    IS DISTINCT FROM v_normalized_snapshot_fingerprint
               OR (v_existing_metadata ->> 'normalized_snapshot_fingerprint_version')
                    IS DISTINCT FROM 'resolved_member_state_jsonb_md5_v1'
               OR (v_existing_metadata ->> 'monotonic_guard_migration')
                    IS DISTINCT FROM '0029_senate_roll_call_provenance' THEN
                RAISE EXCEPTION
                    'conflicting Senate roll-call observation timestamp for % at %',
                    v_roll_call_key,
                    v_fetched_at
                    USING ERRCODE = '23505';
            END IF;

            IF v_existing_session IS DISTINCT FROM v_session
               OR v_existing_vote_date IS DISTINCT FROM v_vote_date
               OR v_existing_question IS DISTINCT FROM v_question
               OR v_existing_vote_result IS DISTINCT FROM v_vote_result
               OR (v_existing_roll_call_metadata ->> 'source')
                    IS DISTINCT FROM 'senate-roll-call-xml' THEN
                RAISE EXCEPTION
                    'conflicting Senate roll-call observation timestamp for % has normalized parent drift',
                    v_roll_call_key
                    USING ERRCODE = '23505';
            END IF;

            PERFORM 1
            FROM public.source_records AS member_source
            WHERE member_source.record_status = 'active'
              AND (
                  member_source.source_record_key LIKE v_roll_call_key || ':%'
                  OR member_source.id IN (
                      SELECT vote.source_record_id
                      FROM public.person_roll_call_votes AS vote
                      WHERE vote.roll_call_source_record_id
                            = v_existing_roll_call_source_record_id
                  )
              )
            ORDER BY member_source.id
            FOR UPDATE;

            PERFORM 1
            FROM public.person_roll_call_votes AS vote
            WHERE vote.roll_call_source_record_id = v_existing_roll_call_source_record_id
            ORDER BY vote.source_record_id
            FOR UPDATE;

            SELECT
                count(*)::integer,
                md5(COALESCE(jsonb_agg(
                    jsonb_build_object(
                        'source_record_key', member_source.source_record_key,
                        'lis_member_id',
                            upper(btrim(member_source.metadata ->> 'lis_member_id')),
                        'bioguide_id',
                            upper(btrim(member_source.metadata ->> 'bioguide_id')),
                        'person_id', member_source.person_id,
                        'identity_crosswalk_source_record_id',
                            member_source.metadata ->> 'identity_crosswalk_source_record_id',
                        'vote_cast', vote.vote_cast,
                        'source_system_key', member_source.source_system_key,
                        'record_type', member_source.record_type,
                        'source_catalog_slug', member_source.source_catalog_slug,
                        'source_endpoint_slug', member_source.source_endpoint_slug,
                        'source_url', member_source.source_url,
                        'raw_payload_ref', member_source.raw_payload_ref,
                        'payload_hash', member_source.payload_hash,
                        'verified_lane', member_source.verified_lane,
                        'record_status', member_source.record_status,
                        'retired_at', member_source.retired_at,
                        'last_seen_at', member_source.last_seen_at,
                        'member_ingestion_method',
                            member_source.metadata ->> 'ingestion_method',
                        'member_raw_xml_retained',
                            member_source.metadata -> 'raw_xml_retained',
                        'identity_crosswalk_source_system',
                            member_source.metadata ->> 'identity_crosswalk_source_system',
                        'vote_metadata_lis_member_id',
                            upper(btrim(vote.metadata ->> 'lis_member_id')),
                        'vote_metadata_bioguide_id',
                            upper(btrim(vote.metadata ->> 'bioguide_id')),
                        'vote_source_matches',
                            vote.source_record_id = member_source.id,
                        'vote_roll_call_matches',
                            vote.roll_call_source_record_id
                                = v_existing_roll_call_source_record_id,
                        'vote_person_matches',
                            vote.person_id = member_source.person_id
                    )
                    ORDER BY member_source.source_record_key
                )::text, '[]'))
            INTO
                v_actual_active_member_count,
                v_actual_snapshot_fingerprint
            FROM public.source_records AS member_source
            LEFT JOIN public.person_roll_call_votes AS vote
              ON vote.source_record_id = member_source.id
            WHERE member_source.record_status = 'active'
              AND (
                  vote.roll_call_source_record_id
                        = v_existing_roll_call_source_record_id
                  OR (
                      member_source.source_system_key = 'senate-lis'
                      AND member_source.source_record_key
                            LIKE v_roll_call_key || ':%'
                  )
              );

            IF v_actual_active_member_count IS DISTINCT FROM v_member_count
               OR v_actual_snapshot_fingerprint
                    IS DISTINCT FROM v_normalized_snapshot_fingerprint THEN
                RAISE EXCEPTION
                    'conflicting Senate roll-call observation timestamp for % has a different active member-vote state',
                    v_roll_call_key
                    USING ERRCODE = '23505';
            END IF;

            RETURN QUERY SELECT
                v_existing_roll_call_source_record_id,
                v_actual_active_member_count;
            RETURN;
        END IF;
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
        'senate-lis',
        v_roll_call_key,
        'legislative_roll_call',
        NULL,
        'senate-roll-call-xml',
        'lis-roll-call-feed',
        v_source_url,
        NULL,
        v_payload_hash,
        'verified',
        'active',
        v_fetched_at,
        v_fetched_at,
        jsonb_build_object(
            'ingestion_method', 'senate_lis_roll_call_xml',
            'raw_xml_retained', false,
            'chamber', 'senate',
            'observation_fingerprint', v_observation_fingerprint,
            'observation_fingerprint_version',
                'payload_sha256_plus_jsonb_args_md5_v1',
            'normalized_snapshot_fingerprint',
                v_normalized_snapshot_fingerprint,
            'normalized_snapshot_fingerprint_version',
                'resolved_member_state_jsonb_md5_v1',
            'monotonic_guard_migration',
                '0029_senate_roll_call_provenance'
        )
    )
    ON CONFLICT (source_system_key, source_record_key) DO UPDATE SET
        source_url = EXCLUDED.source_url,
        raw_payload_ref = NULL,
        payload_hash = EXCLUDED.payload_hash,
        verified_lane = 'verified',
        record_status = 'active',
        retired_at = NULL,
        last_seen_at = EXCLUDED.last_seen_at,
        metadata = (
            public.source_records.metadata
            - 'retirement_reason'
            - 'retired_by_payload_hash'
        ) || EXCLUDED.metadata
    RETURNING id INTO v_existing_roll_call_source_record_id;

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
    WHERE roll_call.source_record_id = v_existing_roll_call_source_record_id
    FOR UPDATE;

    IF FOUND AND (
        v_existing_roll_call_key IS DISTINCT FROM v_roll_call_key
        OR v_existing_chamber IS DISTINCT FROM 'senate'
        OR v_existing_congress IS DISTINCT FROM v_congress
        OR v_existing_session IS DISTINCT FROM v_session
        OR v_existing_congress_year IS DISTINCT FROM v_congress_year
        OR v_existing_roll_call_number IS DISTINCT FROM v_roll_call_number
    ) THEN
        RAISE EXCEPTION
            'existing normalized Senate roll call conflicts with its stable event identity'
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
        v_existing_roll_call_source_record_id,
        v_roll_call_key,
        'senate',
        v_congress,
        v_session,
        v_congress_year,
        v_roll_call_number,
        v_vote_date,
        v_question,
        v_vote_result,
        jsonb_build_object('source', 'senate-roll-call-xml')
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
        ORDER BY upper(btrim(item.value ->> 'lis_member_id'))
    LOOP
        v_lis_member_id := upper(btrim(v_member ->> 'lis_member_id'));
        v_bioguide_id := upper(btrim(v_member ->> 'bioguide_id'));
        v_member_key := format('%s:%s', v_roll_call_key, v_lis_member_id);
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
        END;

        SELECT
            external_id.person_id,
            crosswalk_source.id
        INTO
            v_person_id,
            v_crosswalk_source_record_id
        FROM public.person_external_ids AS external_id
        JOIN public.people AS person
          ON person.id = external_id.person_id
         AND person.status = 'active'
        JOIN public.source_records AS crosswalk_source
          ON crosswalk_source.source_system_key = 'congress-legislators'
         AND crosswalk_source.source_record_key = v_bioguide_id
         AND crosswalk_source.person_id = external_id.person_id
         AND crosswalk_source.record_type = 'person_profile'
         AND crosswalk_source.record_status IN ('active', 'retired')
         AND crosswalk_source.source_catalog_slug = 'congress-legislators'
         AND crosswalk_source.source_endpoint_slug = 'repository'
        JOIN public.politicians AS profile
          ON profile.id = crosswalk_source.legacy_politician_id
         AND upper(btrim(profile.bioguide_id)) = v_bioguide_id
         AND upper(btrim(profile.external_ids ->> 'lis')) = v_lis_member_id
        JOIN public.legacy_profile_redirects AS redirect
          ON redirect.legacy_politician_id = profile.id
         AND redirect.person_id = external_id.person_id
        WHERE external_id.source_system_key = 'bioguide'
          AND external_id.external_id_type = 'bioguide_id'
          AND upper(btrim(external_id.external_id)) = v_bioguide_id
          AND external_id.is_trusted = true;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'Senate member crosswalk disappeared after pre-write validation'
                USING ERRCODE = '23503';
        END IF;

        SELECT
            source.id,
            source.record_type,
            source.person_id,
            source.source_catalog_slug,
            source.source_endpoint_slug,
            source.raw_payload_ref,
            source.verified_lane,
            source.metadata
        INTO
            v_member_source_record_id,
            v_existing_record_type,
            v_existing_record_person_id,
            v_existing_catalog_slug,
            v_existing_endpoint_slug,
            v_existing_member_raw_payload_ref,
            v_existing_member_verified_lane,
            v_existing_member_metadata
        FROM public.source_records AS source
        WHERE source.source_system_key = 'senate-lis'
          AND source.source_record_key = v_member_key
        FOR UPDATE;
        v_member_source_preexisting := FOUND;

        IF v_member_source_preexisting AND (
            v_existing_record_type IS DISTINCT FROM 'person_roll_call_vote'
            OR v_existing_record_person_id IS DISTINCT FROM v_person_id
            OR v_existing_catalog_slug IS DISTINCT FROM 'senate-roll-call-xml'
            OR v_existing_endpoint_slug IS DISTINCT FROM 'lis-roll-call-feed'
            OR v_existing_member_raw_payload_ref IS NOT NULL
            OR v_existing_member_verified_lane IS DISTINCT FROM 'verified'
            OR upper(btrim(v_existing_member_metadata ->> 'lis_member_id'))
                IS DISTINCT FROM v_lis_member_id
            OR upper(btrim(v_existing_member_metadata ->> 'bioguide_id'))
                IS DISTINCT FROM v_bioguide_id
            OR (v_existing_member_metadata ->> 'identity_crosswalk_source_system')
                IS DISTINCT FROM 'congress-legislators'
            OR (v_existing_member_metadata ->> 'identity_crosswalk_source_record_id')
                IS DISTINCT FROM v_crosswalk_source_record_id::text
        ) THEN
            RAISE EXCEPTION
                'existing Senate member-vote source record conflicts with its trusted identity'
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
            'senate-lis',
            v_member_key,
            'person_roll_call_vote',
            v_person_id,
            'senate-roll-call-xml',
            'lis-roll-call-feed',
            v_source_url,
            NULL,
            v_payload_hash,
            'verified',
            'active',
            v_fetched_at,
            v_fetched_at,
            jsonb_build_object(
                'lis_member_id', v_lis_member_id,
                'bioguide_id', v_bioguide_id,
                'identity_crosswalk_source_system', 'congress-legislators',
                'identity_crosswalk_source_record_id',
                    v_crosswalk_source_record_id,
                'ingestion_method', 'senate_lis_roll_call_xml',
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
            last_seen_at = EXCLUDED.last_seen_at,
            metadata = (
                public.source_records.metadata
                - 'retirement_reason'
                - 'retired_by_payload_hash'
            ) || EXCLUDED.metadata
        RETURNING id INTO v_member_source_record_id;

        SELECT
            vote.source_record_id,
            vote.roll_call_source_record_id,
            vote.person_id,
            vote.vote_cast,
            vote.metadata
        INTO
            v_existing_vote_source_record_id,
            v_existing_vote_roll_call_id,
            v_existing_vote_person_id,
            v_existing_vote_cast,
            v_existing_vote_metadata
        FROM public.person_roll_call_votes AS vote
        WHERE vote.source_record_id = v_member_source_record_id
           OR (
               vote.roll_call_source_record_id
                    = v_existing_roll_call_source_record_id
               AND vote.person_id = v_person_id
           )
        ORDER BY (vote.source_record_id = v_member_source_record_id) DESC
        LIMIT 1
        FOR UPDATE;

        IF v_member_source_preexisting AND NOT FOUND THEN
            RAISE EXCEPTION
                'existing Senate member-vote source record is missing its normalized fact'
                USING ERRCODE = '23503';
        END IF;

        IF FOUND AND (
            v_existing_vote_source_record_id IS DISTINCT FROM v_member_source_record_id
            OR v_existing_vote_roll_call_id
                IS DISTINCT FROM v_existing_roll_call_source_record_id
            OR v_existing_vote_person_id IS DISTINCT FROM v_person_id
            OR upper(btrim(v_existing_vote_metadata ->> 'lis_member_id'))
                IS DISTINCT FROM v_lis_member_id
            OR upper(btrim(v_existing_vote_metadata ->> 'bioguide_id'))
                IS DISTINCT FROM v_bioguide_id
        ) THEN
            RAISE EXCEPTION
                'existing Senate member vote conflicts with its stable event or person identity'
                USING ERRCODE = '23505';
        END IF;

        IF FOUND AND v_existing_vote_cast IS DISTINCT FROM v_vote_cast THEN
            RAISE EXCEPTION
                'existing official Senate vote conflicts for roll call % and LIS member ID %; preserving the last valid vote',
                v_roll_call_key,
                v_lis_member_id
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
            v_existing_roll_call_source_record_id,
            v_person_id,
            v_vote_cast,
            jsonb_build_object(
                'lis_member_id', v_lis_member_id,
                'bioguide_id', v_bioguide_id
            )
        )
        ON CONFLICT (source_record_id) DO UPDATE SET
            metadata = public.person_roll_call_votes.metadata || EXCLUDED.metadata;
    END LOOP;

    UPDATE public.source_records AS source
    SET
        record_status = 'retired',
        retired_at = GREATEST(source.last_seen_at, v_fetched_at),
        metadata = source.metadata || jsonb_build_object(
            'retirement_reason',
                'omitted_from_complete_senate_roll_call_snapshot',
            'retired_by_payload_hash', v_payload_hash
        )
    FROM public.person_roll_call_votes AS vote
    WHERE vote.source_record_id = source.id
      AND vote.roll_call_source_record_id
            = v_existing_roll_call_source_record_id
      AND source.source_system_key = 'senate-lis'
      AND source.record_type = 'person_roll_call_vote'
      AND source.record_status = 'active'
      AND NOT (
          COALESCE(upper(btrim(source.metadata ->> 'lis_member_id')), '')
          = ANY(v_supplied_lis_ids)
      );

    RETURN QUERY SELECT
        v_existing_roll_call_source_record_id,
        v_member_count;
END;
$function$;

REVOKE ALL ON FUNCTION public.upsert_senate_roll_call_0029(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated, service_role;

-- Stable public OID for schema preflight and the later reviewed enablement. Any
-- non-preflight call fails independently of catalog state, so an accidental gate
-- flip cannot reach the owner-only helper.
CREATE FUNCTION public.upsert_senate_roll_call(
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
AS $barrier$
BEGIN
    IF jsonb_typeof(p_roll_call) = 'object'
       AND COALESCE(p_roll_call ->> 'preflight', '') = 'true'
       AND p_member_votes = '[]'::jsonb THEN
        RETURN QUERY SELECT NULL::uuid, 0::integer;
        RETURN;
    END IF;

    RAISE EXCEPTION
        'authoritative Senate roll-call writes are disabled pending a separate runtime enablement review'
        USING ERRCODE = '55000';
END;
$barrier$;

REVOKE ALL ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.upsert_senate_roll_call(jsonb, jsonb)
    TO service_role;

DO $function_acl_validation$
DECLARE
    v_public_oid oid := to_regprocedure(
        'public.upsert_senate_roll_call(jsonb,jsonb)'
    );
    v_private_oid oid := to_regprocedure(
        'public.upsert_senate_roll_call_0029(jsonb,jsonb)'
    );
BEGIN
    IF v_public_oid IS NULL OR v_private_oid IS NULL THEN
        RAISE EXCEPTION 'Senate provenance functions were not installed'
            USING ERRCODE = '42883';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc AS procedure
        WHERE procedure.oid = v_public_oid
          AND procedure.prosecdef
          AND procedure.provolatile = 'v'
          AND procedure.proconfig
                IS NOT DISTINCT FROM ARRAY['search_path=""']::text[]
          AND has_function_privilege(
                'service_role',
                procedure.oid,
                'EXECUTE'
          )
          AND NOT has_function_privilege('anon', procedure.oid, 'EXECUTE')
          AND NOT has_function_privilege(
                'authenticated',
                procedure.oid,
                'EXECUTE'
          )
    ) THEN
        RAISE EXCEPTION
            'public Senate write barrier ACL or security contract is invalid'
            USING ERRCODE = '42501';
    END IF;

    IF has_function_privilege('service_role', v_private_oid, 'EXECUTE')
       OR has_function_privilege('anon', v_private_oid, 'EXECUTE')
       OR has_function_privilege('authenticated', v_private_oid, 'EXECUTE') THEN
        RAISE EXCEPTION
            'owner-only Senate write helper is executable by an application role'
            USING ERRCODE = '42501';
    END IF;
END
$function_acl_validation$;

UPDATE public.source_catalog_sources
SET metadata = metadata || jsonb_build_object(
    'ingestion_status', 'write_contract_ready_disabled',
    'production_write_status', 'disabled_pending_runtime_wiring',
    'production_writes_enabled', false,
    'provenance_tables', jsonb_build_array(
        'legislative_roll_calls',
        'person_roll_call_votes'
    ),
    'write_rpc', 'upsert_senate_roll_call',
    'private_write_helper', 'upsert_senate_roll_call_0029',
    'public_write_barrier', 'installed',
    'identity_join_policy',
        'exact_lis_to_bioguide_pair_verified_against_congress_legislators_source_record'
)
WHERE slug = 'senate-roll-call-xml';

UPDATE public.source_catalog_endpoints
SET metadata = metadata || jsonb_build_object(
    'ingestion_status', 'write_contract_ready_disabled',
    'production_write_status', 'disabled_pending_runtime_wiring',
    'production_writes_enabled', false,
    'write_rpc', 'upsert_senate_roll_call',
    'public_write_barrier', 'installed'
)
WHERE source_slug = 'senate-roll-call-xml'
  AND endpoint_slug = 'lis-roll-call-feed';

INSERT INTO public.schema_migrations (
    migration_key,
    migration_version,
    description,
    metadata
)
VALUES (
    '0029_senate_roll_call_provenance',
    29,
    'Reserve the Senate roll-call provenance keyspace and install a write-disabled atomic contract.',
    jsonb_build_object(
        'source_slug', 'senate-roll-call-xml',
        'endpoint_slug', 'lis-roll-call-feed',
        'source_system_key', 'senate-lis',
        'legislative_roll_calls', true,
        'person_roll_call_votes', true,
        'write_rpc', 'upsert_senate_roll_call',
        'private_write_helper', 'upsert_senate_roll_call_0029',
        'public_write_barrier', true,
        'monotonic_observations', true,
        'exact_replay_state_comparison', true,
        'senate_roll_call_source_record_contract', true,
        'trusted_lis_bioguide_crosswalk_required', true,
        'production_writes_enabled', false,
        'scraper_preflight_required', true
    )
);

NOTIFY pgrst, 'reload schema';

COMMIT;
