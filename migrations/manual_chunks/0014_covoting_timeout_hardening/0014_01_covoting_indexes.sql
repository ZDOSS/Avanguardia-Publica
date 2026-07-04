SET statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call_person_vote_active
    ON public.voting_records (roll_call_id, person_id, vote_cast)
    WHERE roll_call_id IS NOT NULL
      AND person_id IS NOT NULL
      AND vote_cast IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_voting_records_roll_call_politician_vote_unresolved
    ON public.voting_records (roll_call_id, politician_id, vote_cast)
    WHERE roll_call_id IS NOT NULL
      AND politician_id IS NOT NULL
      AND person_id IS NULL
      AND vote_cast IS NOT NULL;
