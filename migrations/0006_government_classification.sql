-- Normalize politician office classification so the directory and future analytics
-- can filter by structured fields instead of reparsing current_office text.
--
-- Idempotent and safe to re-run manually in Supabase SQL editor.

ALTER TABLE politicians ADD COLUMN IF NOT EXISTS government_level TEXT;
ALTER TABLE politicians ADD COLUMN IF NOT EXISTS government_branch TEXT;
ALTER TABLE politicians ADD COLUMN IF NOT EXISTS office_type TEXT;
ALTER TABLE politicians ADD COLUMN IF NOT EXISTS jurisdiction TEXT;

COMMENT ON COLUMN politicians.government_level IS
    'Normalized level: federal, state, or local.';
COMMENT ON COLUMN politicians.government_branch IS
    'Normalized branch: executive, legislative, judicial, or source-specific local branch.';
COMMENT ON COLUMN politicians.office_type IS
    'Normalized office type such as senator, representative, governor, mayor, or justice.';
COMMENT ON COLUMN politicians.jurisdiction IS
    'Normalized governing jurisdiction: US for national offices, state code for state offices, or local jurisdiction label when known.';

-- Backfill existing rows from the same conservative classification rules used by
-- the scraper. Existing non-null values are preserved.
UPDATE politicians
SET government_level = COALESCE(
        government_level,
        CASE
            WHEN lower(coalesce(current_office, '')) LIKE '%state senator%'
              OR lower(coalesce(current_office, '')) LIKE '%state senate%'
              OR lower(coalesce(current_office, '')) LIKE '%state representative%'
              OR lower(coalesce(current_office, '')) LIKE '%state assembly%'
              OR lower(coalesce(current_office, '')) LIKE '%state house%'
              OR lower(coalesce(current_office, '')) LIKE '%house of delegates%'
              OR lower(coalesce(current_office, '')) LIKE '%assembly member%'
              OR lower(coalesce(current_office, '')) LIKE '%lieutenant governor%'
              OR lower(coalesce(current_office, '')) LIKE 'governor of%'
              OR external_ids ? 'openstates'
                THEN 'state'
            WHEN bioguide_id IS NOT NULL
              OR lower(coalesce(current_office, '')) LIKE '%president of the united states%'
              OR lower(coalesce(current_office, '')) LIKE '%vice president%'
              OR lower(coalesce(current_office, '')) LIKE '%u.s. senator%'
              OR lower(coalesce(current_office, '')) LIKE '%us senator%'
              OR lower(coalesce(current_office, '')) LIKE '%united states senator%'
              OR lower(coalesce(current_office, '')) LIKE '%senator from%'
              OR lower(coalesce(current_office, '')) LIKE '%u.s. representative%'
              OR lower(coalesce(current_office, '')) LIKE '%us representative%'
              OR lower(coalesce(current_office, '')) LIKE '%representative from%'
              OR lower(coalesce(current_office, '')) LIKE '%member of congress%'
              OR lower(coalesce(current_office, '')) LIKE '%house of representatives%'
              OR lower(coalesce(current_office, '')) LIKE '%chief justice%'
              OR lower(coalesce(current_office, '')) LIKE '%associate justice%'
              OR lower(coalesce(current_office, '')) LIKE '%supreme court%'
                THEN 'federal'
            WHEN lower(coalesce(current_office, '')) LIKE '%mayor%'
              OR lower(coalesce(current_office, '')) LIKE '%city manager%'
              OR lower(coalesce(current_office, '')) LIKE '%town administrator%'
              OR lower(coalesce(current_office, '')) LIKE '%city council%'
              OR lower(coalesce(current_office, '')) LIKE '%alderman%'
              OR lower(coalesce(current_office, '')) LIKE '%alderperson%'
              OR lower(coalesce(current_office, '')) LIKE '%town board%'
              OR lower(coalesce(current_office, '')) LIKE '%sheriff%'
              OR lower(coalesce(current_office, '')) LIKE '%district attorney%'
              OR lower(coalesce(current_office, '')) LIKE '%county prosecutor%'
              OR lower(coalesce(current_office, '')) LIKE '%county commissioner%'
              OR lower(coalesce(current_office, '')) LIKE '%county executive%'
              OR lower(coalesce(current_office, '')) LIKE '%county supervisor%'
              OR lower(coalesce(current_office, '')) LIKE '%board of supervisors%'
              OR lower(coalesce(current_office, '')) LIKE '%school board%'
              OR lower(coalesce(current_office, '')) LIKE '%board of education%'
              OR lower(coalesce(current_office, '')) LIKE '%school district%'
              OR lower(coalesce(current_office, '')) LIKE '%county%'
                THEN 'local'
            ELSE NULL
        END
    );

UPDATE politicians
SET government_branch = COALESCE(
        government_branch,
        CASE
            WHEN lower(coalesce(current_office, '')) LIKE '%chief justice%'
              OR lower(coalesce(current_office, '')) LIKE '%associate justice%'
              OR lower(coalesce(current_office, '')) LIKE '%supreme court%'
                THEN 'judicial'
            WHEN lower(coalesce(current_office, '')) LIKE '%senator%'
              OR lower(coalesce(current_office, '')) LIKE '%representative%'
              OR lower(coalesce(current_office, '')) LIKE '%state senate%'
              OR lower(coalesce(current_office, '')) LIKE '%state house%'
              OR lower(coalesce(current_office, '')) LIKE '%house of delegates%'
              OR lower(coalesce(current_office, '')) LIKE '%assembly member%'
              OR lower(coalesce(current_office, '')) LIKE '%member of congress%'
              OR lower(coalesce(current_office, '')) LIKE '%city council%'
              OR lower(coalesce(current_office, '')) LIKE '%alderman%'
              OR lower(coalesce(current_office, '')) LIKE '%alderperson%'
              OR lower(coalesce(current_office, '')) LIKE '%town board%'
              OR lower(coalesce(current_office, '')) LIKE '%county commissioner%'
              OR lower(coalesce(current_office, '')) LIKE '%county supervisor%'
              OR lower(coalesce(current_office, '')) LIKE '%board of supervisors%'
              OR lower(coalesce(current_office, '')) LIKE '%school board%'
              OR lower(coalesce(current_office, '')) LIKE '%board of education%'
                THEN 'legislative'
            WHEN government_level IN ('federal', 'state', 'local')
                THEN 'executive'
            ELSE NULL
        END
    );

UPDATE politicians
SET office_type = COALESCE(
        office_type,
        CASE
            WHEN lower(coalesce(current_office, '')) LIKE '%lieutenant governor%' THEN 'lieutenant_governor'
            WHEN lower(coalesce(current_office, '')) LIKE 'governor of%' THEN 'governor'
            WHEN lower(coalesce(current_office, '')) LIKE '%vice president%' THEN 'vice_president'
            WHEN lower(coalesce(current_office, '')) LIKE '%president of the united states%' THEN 'president'
            WHEN lower(coalesce(current_office, '')) LIKE '%chief justice%' THEN 'chief_justice'
            WHEN lower(coalesce(current_office, '')) LIKE '%associate justice%'
              OR lower(coalesce(current_office, '')) LIKE '%supreme court%'
                THEN 'associate_justice'
            WHEN lower(coalesce(current_office, '')) LIKE '%senator%'
              OR lower(coalesce(current_office, '')) LIKE '%state senate%'
                THEN 'senator'
            WHEN lower(coalesce(current_office, '')) LIKE '%representative%'
              OR lower(coalesce(current_office, '')) LIKE '%state assembly%'
              OR lower(coalesce(current_office, '')) LIKE '%state house%'
              OR lower(coalesce(current_office, '')) LIKE '%house of delegates%'
              OR lower(coalesce(current_office, '')) LIKE '%assembly member%'
              OR lower(coalesce(current_office, '')) LIKE '%member of congress%'
                THEN 'representative'
            WHEN lower(coalesce(current_office, '')) LIKE '%mayor%' THEN 'mayor'
            WHEN lower(coalesce(current_office, '')) LIKE '%city manager%' THEN 'city_manager'
            WHEN lower(coalesce(current_office, '')) LIKE '%town administrator%' THEN 'town_administrator'
            WHEN lower(coalesce(current_office, '')) LIKE '%city council%'
              OR lower(coalesce(current_office, '')) LIKE '%alderman%'
              OR lower(coalesce(current_office, '')) LIKE '%alderperson%'
              OR lower(coalesce(current_office, '')) LIKE '%town board%'
                THEN 'council_member'
            WHEN lower(coalesce(current_office, '')) LIKE '%sheriff%' THEN 'sheriff'
            WHEN lower(coalesce(current_office, '')) LIKE '%district attorney%'
              OR lower(coalesce(current_office, '')) LIKE '%county prosecutor%'
                THEN 'district_attorney'
            WHEN lower(coalesce(current_office, '')) LIKE '%county commissioner%'
              OR lower(coalesce(current_office, '')) LIKE '%county executive%'
              OR lower(coalesce(current_office, '')) LIKE '%county supervisor%'
              OR lower(coalesce(current_office, '')) LIKE '%board of supervisors%'
                THEN 'county_commissioner'
            WHEN lower(coalesce(current_office, '')) LIKE '%school board%'
              OR lower(coalesce(current_office, '')) LIKE '%board of education%'
              OR lower(coalesce(current_office, '')) LIKE '%school district%'
                THEN 'school_board_member'
            ELSE NULL
        END
    );

UPDATE politicians
SET jurisdiction = COALESCE(
        jurisdiction,
        CASE
            WHEN government_level = 'federal' THEN 'US'
            WHEN government_level = 'state' THEN state
            ELSE NULL
        END
    );

CREATE INDEX IF NOT EXISTS idx_politicians_government_level
    ON politicians (government_level);

CREATE INDEX IF NOT EXISTS idx_politicians_government_classification
    ON politicians (government_level, government_branch, office_type);

CREATE INDEX IF NOT EXISTS idx_politicians_jurisdiction
    ON politicians (jurisdiction);

-- Keep full-text search useful when normalized labels are present.
CREATE OR REPLACE FUNCTION update_politicians_search_vector()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.search_vector :=
        to_tsvector(
            'english',
            coalesce(NEW.full_name, '') || ' ' ||
            coalesce(NEW.current_office, '') || ' ' ||
            coalesce(NEW.party, '') || ' ' ||
            coalesce(NEW.government_level, '') || ' ' ||
            coalesce(NEW.government_branch, '') || ' ' ||
            coalesce(NEW.office_type, '') || ' ' ||
            coalesce(NEW.jurisdiction, '') || ' ' ||
            coalesce(array_to_string(NEW.aliases, ' '), '')
        );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS politicians_search_vector_update ON politicians;
CREATE TRIGGER politicians_search_vector_update
    BEFORE INSERT OR UPDATE OF full_name, current_office, party, aliases,
        government_level, government_branch, office_type, jurisdiction
    ON politicians
    FOR EACH ROW
    EXECUTE FUNCTION update_politicians_search_vector();
