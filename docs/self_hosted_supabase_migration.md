# Self-Hosted Supabase Migration Checkpoint

This project should migrate from managed Supabase to the Ubuntu 24.04 VPS after the
Phase 2 covoting timeout fix is merged and before Phase 3 scraper identity work starts.

## Why self-hosted Supabase, not bare Postgres

The static GitHub Pages frontend calls Supabase-compatible browser APIs directly:

- `/rest/v1/rpc/...` for profile RPCs and search
- anon-key authenticated reads from the generated REST API
- service-key writes from the Python scraper

A plain Postgres server would not expose those APIs. The lowest-risk VPS target is therefore
self-hosted Supabase, or an explicitly compatible PostgREST/Kong/JWT stack. Supabase's
current self-hosting docs recommend Docker Compose as the fastest path:

- https://supabase.com/docs/guides/self-hosting
- https://supabase.com/docs/guides/self-hosting/docker
- https://supabase.com/docs/guides/self-hosting/restore-from-platform

## Cutover order

1. Merge and apply `migrations/0014_covoting_timeout_hardening.sql` if managed Supabase can
   still handle it.
2. Pause scraper runs and feature migrations.
3. Stand up self-hosted Supabase on the VPS.
4. Restore the managed Supabase database dump into the self-hosted database.
5. Verify extensions, tables, RLS policies, grants, and public RPC execution.
6. Apply any migration that was not already present on the dump target.
7. Update GitHub Actions secrets:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
8. Redeploy the frontend so the static bundle points at the VPS-backed Supabase URL.
9. Run one controlled scraper pass against the VPS.
10. Resume the canonical roadmap with Phase 3.

## Validation checks

Run these before switching production traffic:

```sql
select count(*) from public.people;
select count(*) from public.legacy_profile_redirects;
select count(*) from public.voting_records where person_id is not null;
select count(*) from public.relationships where person_id is not null;

select *
from public.get_canonical_politician_summaries('A.J. Lou', 5, 0);

select *
from public.get_covoting('13b55892-fedb-5a23-b3c6-d363f23e5e73'::uuid);
```

The frontend should also be spot-checked at:

- `https://zdoss.github.io/Avanguardia-Publica/`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=9cc83a98-d844-5fdf-b323-234654b20ec2`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=13b55892-fedb-5a23-b3c6-d363f23e5e73`
- `https://zdoss.github.io/Avanguardia-Publica/profile?id=587e7f7a-6410-55c2-a21b-5d085fd5dc9f`

## Operational notes

- Self-hosted Supabase is community-supported. The VPS owner is responsible for OS updates,
  Docker updates, backups, monitoring, uptime, and disaster recovery.
- Use HTTPS in production before pointing the public frontend at the VPS.
- Generate fresh self-hosted API keys and do not reuse managed Supabase secrets.
- Existing auth tokens from managed Supabase will not be valid if the JWT secret changes.
  This app is currently public-read, so that should not affect public profile viewing.
- Keep the old managed Supabase project read-only until the first VPS scraper run and
  frontend deploy are confirmed.
