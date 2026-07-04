# 0013 Manual Chunks

Run these files in order in the Supabase SQL editor after PR 52 is merged.

Each file includes:

```sql
SET statement_timeout = '30s';
```

Order:

1. `0013_01_search_name_indexes.sql`
2. `0013_02_voting_person_roll_call_index.sql`
3. `0013_03_voting_politician_roll_call_index.sql`
4. `0013_04_voting_roll_call_vote_person_index.sql`
5. `0013_05_search_rpc.sql`
6. `0013_06_covoting_rpc.sql`
7. `0013_07_permissions_reload.sql`

If an index chunk times out, stop and report the exact file name. Do not rerun it many
times. The RPC and permission chunks should be quick.
