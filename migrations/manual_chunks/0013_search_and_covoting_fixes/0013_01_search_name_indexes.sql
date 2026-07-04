SET statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_politicians_full_name_lower_prefix
    ON public.politicians (lower(full_name) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_people_primary_name_lower_prefix
    ON public.people (lower(primary_name) text_pattern_ops);

CREATE INDEX IF NOT EXISTS idx_people_primary_name_search_vector
    ON public.people
    USING gin (to_tsvector('english', coalesce(primary_name, '')));
