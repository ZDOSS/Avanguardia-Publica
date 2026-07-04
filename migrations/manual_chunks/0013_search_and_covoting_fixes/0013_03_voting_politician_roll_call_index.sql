SET statement_timeout = '30s';

CREATE INDEX IF NOT EXISTS idx_voting_records_politician_roll_call_active
    ON public.voting_records (politician_id, roll_call_id, vote_cast)
    WHERE roll_call_id IS NOT NULL
      AND vote_cast IS NOT NULL;
