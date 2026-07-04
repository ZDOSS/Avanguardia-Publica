SET statement_timeout = '30s';

CREATE OR REPLACE FUNCTION public.get_covoting(p_id uuid)
RETURNS TABLE (
    politician_id uuid,
    full_name text,
    current_office text,
    party text,
    agree_count bigint,
    disagree_count bigint,
    shared_total bigint,
    agreement_rate numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH target_legacy AS MATERIALIZED (
        SELECT *
        FROM public.get_canonical_person_legacy_ids(p_id)
    ),
    target_person AS MATERIALIZED (
        SELECT person_id
        FROM target_legacy
        LIMIT 1
    ),
    target_vote_candidates AS MATERIALIZED (
        SELECT
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN target_person AS tp ON tp.person_id = vr.person_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL

        UNION ALL

        SELECT
            vr.roll_call_id,
            vr.vote_cast
        FROM public.voting_records AS vr
        JOIN target_legacy AS tl ON tl.legacy_politician_id = vr.politician_id
        WHERE vr.roll_call_id IS NOT NULL
          AND vr.vote_cast IS NOT NULL
    ),
    target_votes AS MATERIALIZED (
        SELECT DISTINCT ON (roll_call_id)
            roll_call_id,
            vote_cast
        FROM target_vote_candidates
        ORDER BY roll_call_id, vote_cast
    ),
    other_vote_candidates AS MATERIALIZED (
        SELECT
            vr.person_id,
            vr.roll_call_id,
            vr.vote_cast
        FROM target_votes AS mine
        JOIN public.voting_records AS vr
          ON vr.roll_call_id = mine.roll_call_id
        CROSS JOIN target_person AS tp
        WHERE vr.person_id IS NOT NULL
          AND vr.person_id <> tp.person_id
          AND vr.vote_cast IS NOT NULL

        UNION ALL

        SELECT
            l.person_id,
            vr.roll_call_id,
            vr.vote_cast
        FROM target_votes AS mine
        JOIN public.voting_records AS vr
          ON vr.roll_call_id = mine.roll_call_id
        JOIN public.legacy_profile_redirects AS l
          ON l.legacy_politician_id = vr.politician_id
        CROSS JOIN target_person AS tp
        WHERE vr.person_id IS NULL
          AND l.person_id <> tp.person_id
          AND vr.vote_cast IS NOT NULL
    ),
    other_votes AS MATERIALIZED (
        SELECT DISTINCT ON (person_id, roll_call_id)
            person_id,
            roll_call_id,
            vote_cast
        FROM other_vote_candidates
        ORDER BY person_id, roll_call_id, vote_cast
    ),
    scored_people AS MATERIALIZED (
        SELECT
            ov.person_id,
            count(*) FILTER (WHERE ov.vote_cast = tv.vote_cast) AS agree_count,
            count(*) FILTER (WHERE ov.vote_cast <> tv.vote_cast) AS disagree_count,
            count(*) AS shared_total,
            round(
                count(*) FILTER (WHERE ov.vote_cast = tv.vote_cast)::numeric
                / NULLIF(count(*), 0),
                3
            ) AS agreement_rate
        FROM other_votes AS ov
        JOIN target_votes AS tv ON tv.roll_call_id = ov.roll_call_id
        GROUP BY ov.person_id
        ORDER BY count(*) DESC, GREATEST(
            count(*) FILTER (WHERE ov.vote_cast = tv.vote_cast),
            count(*) FILTER (WHERE ov.vote_cast <> tv.vote_cast)
        ) DESC
        LIMIT 30
    ),
    ranked_headers AS (
        SELECT
            sp.person_id,
            p.full_name,
            p.current_office,
            p.party,
            row_number() OVER (
                PARTITION BY sp.person_id
                ORDER BY
                    COALESCE(l.legacy_politician_id = l.canonical_politician_id, false) DESC,
                    p.last_updated DESC NULLS LAST,
                    p.id
            ) AS profile_rank
        FROM scored_people AS sp
        LEFT JOIN public.legacy_profile_redirects AS l ON l.person_id = sp.person_id
        LEFT JOIN public.politicians AS p ON p.id = l.legacy_politician_id
    )
    SELECT
        sp.person_id AS politician_id,
        COALESCE(pe.primary_name, rh.full_name) AS full_name,
        rh.current_office,
        rh.party,
        sp.agree_count,
        sp.disagree_count,
        sp.shared_total,
        sp.agreement_rate
    FROM scored_people AS sp
    LEFT JOIN ranked_headers AS rh
      ON rh.person_id = sp.person_id
     AND rh.profile_rank = 1
    LEFT JOIN public.people AS pe ON pe.id = sp.person_id AND pe.status = 'active'
    ORDER BY sp.shared_total DESC, GREATEST(sp.agree_count, sp.disagree_count) DESC;
$$;
