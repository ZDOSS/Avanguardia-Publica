SET statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_voting_records_person_roll_call_active
    ON public.voting_records (person_id, roll_call_id, vote_cast)
    WHERE person_id IS NOT NULL
      AND roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;
