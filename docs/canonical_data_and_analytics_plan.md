# Canonical Data And Analytics Plan

This is the active roadmap for remaining data-model, scraper, profile, search, directory,
and analytics work. It supersedes the former separate roadmap docs, which were removed to
avoid split-source planning.

This plan tracks the current implementation frontier. Phase 1 is retained because Phase 2
depends on its compatibility contract, but new implementation should start from the first
unfinished Phase 2 item unless the Phase 1 bridge needs a bug fix.

## Goal

Move the app from legacy `politicians.id` identity to durable canonical person identity,
then build analytics on top of canonical people and role-aware data.

The practical test: a real person appears once in profile, search, directory, and analytics
even when multiple sources or legacy rows describe that person.

## Core Rules

- A person is not federal, state, or local. A person has roles.
- `people.id` is the durable identity target.
- Legacy `politicians.id` values must keep working through `/profile?id=<uuid>`.
- Existing `politicians.government_level`, `government_branch`, `office_type`, and
  `jurisdiction` are compatibility fields only. Do not copy them as person-level fields
  onto `people`.
- Do not auto-merge fuzzy identity matches. Fuzzy candidates go to review.
- Do not build new analytics over raw `politicians.id` once the identity bridge starts.
  Use `person_id` or an identity-aware compatibility RPC.
- Verified and unverified data must remain visually and semantically distinct.
- Migrations are manual, idempotent, and must be safe to re-run.
- New data sources must remain free-tier or open source.

## Phase 1: Canonical Identity Bridge (Implemented)

Implemented by `migrations/0011_canonical_identity_bridge.sql`, the live profile/search
RPC updates, scraper schema preflight checks, deterministic identity rule tests, and the
loader's `sync_legacy_profile_identity` call after hub upserts.

Fix duplicate profiles by adding an explicit identity bridge without replacing the whole
schema.

Add the smallest useful canonical layer:

- `people`
- `person_external_ids`
- `person_names`
- `legacy_profile_redirects` or an equivalent legacy mapping table
- `identity_resolution_candidates`
- `person_merge_events` if the implementation marks or merges canonical `people` rows
- `source_systems`

Required behavior:

- `/profile?id=<legacy-politician-uuid>` resolves to the canonical `people.id`.
- `/profile?id=<person-uuid>` renders the active canonical person.
- Search and directory return one row per active `people.id`.
- Known duplicate legacy profile UUIDs map to one canonical person.
- The current profile spokes keep working during the transition.

Until spoke tables have `person_id`, profile read surfaces must not resolve only the
header. They must either query all legacy `politicians.id` rows mapped to the canonical
person, or use a deliberately chosen compatibility RPC that preserves spoke data from all
mapped rows.

Deterministic auto-attach signals:

- Same constrained `politicians.bioguide_id`.
- Same trusted external ID from a curated namespace, such as OpenStates person ID,
  GovTrack person ID, FEC candidate ID, FJC judge ID, or Wikidata QID when sourced from a
  trusted crosswalk.
- Existing manually approved legacy redirect/backfill mapping.

Do not auto-attach on name, party, office title, social handle, or unconstrained stale JSON
external IDs alone.

Implementation requirements:

- Add schema preflight checks for the new identity tables and RPCs.
- Seed current source systems, including legacy Avanguardia profile IDs and trusted
  government/open-data sources used by the scraper.
- Add regression coverage for the live duplicate UUIDs that exposed the bug.
- Add validation queries for duplicate external IDs, unmapped legacy rows, and pending
  identity candidates.
- Add tests proving same-name records without deterministic identity do not merge, and
  conflicting deterministic IDs remain separate or review-blocked.
- Keep compatibility fallbacks for deployments where the migration has not yet been run.
- Do not add the full government role/entity taxonomy in this phase.

Merge and redirect rules:

- Prefer the survivor with the strongest official external ID, then the most complete
  attached data, then the oldest created record.
- Record canonical person merges in `person_merge_events` when canonical `people` rows are
  merged.
- Preserve every legacy profile UUID through `legacy_profile_redirects`.
- Resolve uniqueness conflicts by preserving the higher-trust fact and keeping lower-trust
  evidence as provenance or review material.
- Do not move child spoke rows destructively until Phase 2 has a tested `person_id`
  backfill path.

## Phase 2: Person-Aware Profile Spokes (Current)

The first Phase 2 slice is `migrations/0012_person_aware_profile_spokes.sql`: add nullable
`person_id` columns to existing spoke tables, backfill them from `legacy_profile_redirects`,
index them, keep `politician_id`, and have future ETL writes stamp both IDs.

Move profile spoke reads from legacy politician identity to canonical person identity.

For each spoke currently keyed by `politician_id`:

1. Add nullable `person_id`.
2. Backfill `person_id` from the identity bridge.
3. Add an index on `person_id`.
4. Update frontend helpers or RPCs to query by canonical person.
5. Keep `politician_id` through at least one release for rollback.

Affected spokes include:

- contact info
- financial disclosures
- campaign donors
- voting records
- media mentions
- relationships/connections
- future profile tabs

Acceptance criteria:

- Profile tabs for a canonical person include data from all mapped legacy rows.
- Same-person duplicate rows no longer split donor, vote, contact, media, or relationship
  data across profiles.
- Directory/search/profile agree on the same canonical identity.
- Legacy profile URLs still render useful data.

Remaining profile UX improvements should happen after the reads are identity-aware:

- deep links for tabs, such as `/profile?id=<uuid>&tab=votes`
- sorting and filtering inside high-volume tabs
- clear empty states that distinguish unavailable, not-yet-ingested, and not-applicable
  data
- source/freshness labels that use the provenance fields added by this roadmap

## Phase 3: Scraper Identity Resolver

Stop letting scraper upserts create identity implicitly through `upsert_politician`.

Before starting Phase 3, complete the managed Supabase to VPS cutover described in
[`self_hosted_supabase_migration.md`](self_hosted_supabase_migration.md). The frontend and
scraper rely on Supabase-compatible REST/RPC behavior, so the VPS target should be
self-hosted Supabase or an explicitly compatible API stack, not bare Postgres alone.

Add identity modules:

- `scraper/identity/types.py`
- `scraper/identity/normalization.py`
- `scraper/identity/resolver.py`

Extractor output should become normalized facts or packets. The loader resolves the person
first, then writes spokes and compatibility data.

Packets should carry source key, source record key, source URL, raw payload reference,
names, trusted external IDs, roles/spoke facts, and confidence/review metadata. Keep raw
source display names separate from normalized names.

Resolver rules:

- Deterministic ID matches can attach automatically.
- Fuzzy scoring can write review candidates, but cannot auto-merge.
- Conflicting deterministic IDs must halt or queue review rather than overwrite identity.
- Do not overwrite high-trust non-null values with lower-trust nulls.
- Preserve source provenance enough to debug why a fact was attached.

ETL reporting should include identity-specific counts:

- people created
- legacy rows mapped
- deterministic matches
- pending candidates
- blocked conflicts

## Phase 4: Role And Source Model

Add the broader government model only after canonical identity and person-aware spokes are
stable.

Add role/entity tables incrementally, in the order demanded by real loader/frontend use
cases:

- jurisdictions
- districts
- organizations
- offices
- person office terms
- organization memberships
- appointments/nominations
- elections, contests, candidacies, results
- campaign committees
- source records/provenance

Rules:

- Start with the smallest role tables needed by the next source or UI feature.
- Do not add the entire taxonomy in one migration unless the loader and read surface are
  part of the same tested change.
- Government level, branch, office type, and jurisdiction should become role-derived read
  fields, not person identity fields.
- Source metadata should capture source name, source URL or record ID, ingestion method,
  last fetched timestamp, verified/unverified lane, and enough raw payload/hash data to
  debug source conflicts without bloating public read responses.
- Hard constraints that assume perfect seat modeling should begin as validation queries
  until the source data is reliable enough to enforce them.

## Phase 5: Canonical Search, Directory, And Filters

Replace legacy search/directory compatibility with canonical person read surfaces.

Required behavior:

- One search result per active `people.id`.
- One directory row per active `people.id`.
- Filters use role-derived fields where available.
- Legacy normalized `politicians` fields remain fallback only while the role model is
  incomplete.
- Typo-tolerant search is allowed for discovery, never for verified identity joins.

This phase should also decide whether legacy pretty `/[politician_id]` pages remain useful
for SEO, and if so, whether their headers should re-fetch canonical data client-side.

## Phase 6: Data Quality Workflow

Add private or maintainer-facing workflows for unresolved data issues.

Track:

- pending identity candidates
- suspected duplicates
- source mismatches
- unresolved relationship names
- failed enrichments
- stale source records

This can start as SQL validation reports or ETL summary sections before becoming a UI.
Do not expose unreviewed identity decisions as public facts.

## Phase 7: Canonical Analytics RPCs

Build analytics only after identity-aware reads exist.

Candidate RPCs/views:

- shared donor overlap by person
- donor bridge view across canonical people
- voting agreement/opposition by person and jurisdiction
- two-hop organization/person relationship overlap
- same-state, same-chamber, and same-office cohorts
- media co-mention discovery signals
- disclosure filing timelines and filing-type summaries

Rules:

- Analytics must use `person_id` or role-aware canonical read models.
- Verified official records and unverified network/media data must stay separate.
- Wording should describe recorded overlap, not imply causation or influence.
- Every aggregate should link back to source records or underlying profile tabs where
  practical.
- Disclosure analytics remain filing-level until PDF parsing has been implemented and
  verified. Do not imply asset-level analysis from filing-index data alone.

## Phase 8: Visual Analytics

Build visual views on top of canonical analytics RPCs.

Candidate views:

- profile-level connection map
- state dashboard
- donor/PAC explorer
- voting cluster view
- data freshness dashboard

Rules:

- Mobile readability comes before complex graph interactions.
- Verified and unverified data must not share the same visual treatment.
- Charts should expose records or links behind the aggregate.
- Prefer inspectable views over decorative dashboards.

## Phase 9: Cleanup

After canonical identity, spokes, scraper writes, and canonical read surfaces are stable:

- Replace direct `politicians` reads with views or RPCs over `people`.
- Keep old profile UUID redirects permanently.
- Treat `politicians` as a compatibility table or replace it with a compatibility view.
- Remove temporary read-time canonical politician rollups once the bridge covers the same
  cases.
- Remove fallback frontend paths only after the live database has the required migrations.

## Migration Guardrails

Every schema change in this plan must follow these rules:

- Use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
- PostgreSQL does not support `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS`; use `DO $$`
  blocks that check `pg_constraint`.
- Index every foreign key column used for joins or cascades.
- Add `updated_at` triggers where `updated_at` exists.
- Add explicit `GRANT EXECUTE` for frontend RPCs to `anon` and `authenticated`.
- Prefer `SECURITY DEFINER` RPCs with `SET search_path = ''` for public read surfaces.
- Define RLS/direct table policies intentionally; do not rely on accidental public access.
- Avoid materialized views unless the migration defines a unique index, refresh strategy,
  and deployment expectation.
- End schema-changing migrations with `NOTIFY pgrst, 'reload schema';` when new PostgREST
  surfaces must be visible immediately.

## Next PR

The current implementation PR should stay Phase 2 only: nullable `person_id` columns on
existing profile spokes, deterministic backfill from the identity bridge, ETL writes that
stamp `person_id`, preflight checks for the new columns, and compatibility RPCs that keep
legacy `politician_id` fallbacks.

Do not remove legacy `politician_id`, add new analytics features, or add the full
role/entity taxonomy in that PR.
