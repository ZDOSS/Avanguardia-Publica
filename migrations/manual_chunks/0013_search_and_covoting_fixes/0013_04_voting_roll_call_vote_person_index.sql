SET statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call_vote_person_active
    ON public.voting_records (roll_call_id, vote_cast, person_id)
    WHERE roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;
