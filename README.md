# Avanguardia Publica

> The unvarnished public record index.

Avanguardia Publica is a public-facing political-data transparency tool. It aggregates,
classifies, and displays publicly available information about U.S. politicians across the
Federal, State, and Local levels, presenting it as a clean, read-only encyclopedia.

The project follows a **decoupled, zero-cost architecture**: a Python ETL pipeline pushes
data into Supabase on a schedule, and a statically-exported Next.js frontend reads from it.
The render model is **static export with live client data**: home/search, `/directory`,
`/profile?id=<uuid>`, and the profile contact / financial / donor / voting / media /
connections spokes query Supabase **live in the browser**. The legacy pretty
`/[politician_id]` route list is still generated at build time for GitHub Pages, but its
profile spokes now hydrate from the browser once the page exists. Read
[`AGENTS.md`](AGENTS.md) → "Render model" before touching any data-fetching code.

---

## Architecture

```
┌────────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Scraper (Python)  │ ──▶ │ Supabase (Postgres)│ ◀── │ Frontend (Next.js)  │
│  GitHub Actions    │     │  REST API          │     │  Static export →    │
│  (nightly sync)    │     │                    │     │  GitHub Pages       │
└────────────────────┘     └──────────────────┘     └─────────────────────┘
```

| Layer        | Tech                                             | Notes                                              |
| ------------ | ------------------------------------------------ | -------------------------------------------------- |
| Database/API | Supabase (PostgreSQL)                            | Auto-generated REST API; "Hub-and-Spoke" schema    |
| Ingestion    | Python + GitHub Actions                          | Free-tier / open-source data sources only          |
| Frontend     | Next.js (App Router) + React 19 + Tailwind CSS 4 | `output: 'export'` — home/search, `/directory`, `/profile?id=<uuid>`, and profile spokes read live in the browser; pretty dynamic route availability is build-time |
| Hosting      | GitHub Pages (frontend) + GitHub Actions (ETL)   | Zero-cost                                           |

See [`spec.md`](spec.md) for the full product/technical spec,
[`docs/canonical_data_and_analytics_plan.md`](docs/canonical_data_and_analytics_plan.md)
for the active remaining roadmap, and [`AGENTS.md`](AGENTS.md) for architecture handoff
notes.

---

## Repository layout

```
.
├── frontend/          # Next.js app (statically exported to GitHub Pages)
│   └── src/
│       ├── app/       # Routes: / (search), /directory, /[politician_id]
│       └── lib/       # Supabase client + data helpers
├── scraper/           # Python ETL pipeline
│   ├── main.py        # Entry point
│   ├── loader.py      # Supabase upsert logic
│   └── extractors/    # Per-source extractors (fec, federal, govtrack, news, …)
├── migrations/        # SQL migrations
├── schema.sql         # Database schema blueprint
└── .github/workflows/ # nextjs.yml (deploy) + scraper.yml (nightly ETL)
```

---

## Prerequisites

- **Node.js** 20.19+ LTS (or 22.13+) and npm (frontend)
- **Python** 3.10+ and pip (scraper)
- A **Supabase** project (free tier) — or run with the built-in mock data for a quick look

---

## Getting started

### 1. Frontend

```bash
cd frontend
npm install

# Configure environment (see example.env)
cp example.env .env.local
#   NEXT_PUBLIC_SUPABASE_URL=https://<your-project>.supabase.co
#   NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-anon-key>

npm run dev          # http://localhost:3000
```

Without Supabase credentials the app falls back to a small set of mock politicians, so
`npm run dev` works out of the box.

Useful scripts:

| Command         | Description                                  |
| --------------- | -------------------------------------------- |
| `npm run dev`   | Start the dev server                         |
| `npm run build` | Production build + static export to `out/`   |
| `npm run lint`  | Run ESLint                                    |
| `npm run typecheck` | Run the TypeScript compiler without emitting files |

### 2. Scraper

```bash
cd scraper
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure environment (see scraper/example.env)
cp example.env .env
#   Fill in SUPABASE_URL, SUPABASE_KEY (service role), and any data-source API keys

python main.py

# Validate the live schema and latest migration marker without starting the ETL
python main.py --preflight-only
```

The preflight-only command requires `SUPABASE_URL` and `SUPABASE_KEY`. It runs the same
non-mutating table, migration-marker, and RPC checks used at the start of a normal run,
prints `ETL_SUMMARY_JSON`, and exits before extractors, source quotas, or ETL writes.
Use it after applying a migration and before starting a long scraper run.

All scraper data sources are **free-tier or open-source** (no paid APIs). The news
aggregator uses a multi-tier circuit-breaker strategy (Currents → NewsData.io →
approved TheNewsAPI usage → GDELT URL discovery) so it degrades gracefully under rate
limits without scraping article bodies.

Free access and republication rights are different questions. Production extractors must
follow [`docs/source_usage_policy.md`](docs/source_usage_policy.md): retain stable provenance,
store only the fields permitted by the provider, keep required attribution, and keep
ambiguous terms disabled until a maintainer records approval.

Financial disclosures are sourced from the official **U.S. House Clerk** bulk feed
(`disclosures-clerk.house.gov`, keyless). That feed publishes the filing *index* — who filed
which disclosure (Periodic Transaction Report / Annual) on what date, plus a link to the
official PDF — but not the per-transaction asset/value rows, which live inside the PDF. The
profile tab therefore lists filings with a link to each official document. Senate and state
financial disclosures are not yet covered.

---

## Environment variables

| Variable                        | Used by  | Required | Purpose                                              |
| ------------------------------- | -------- | -------- | ---------------------------------------------------- |
| `NEXT_PUBLIC_SUPABASE_URL`      | frontend | yes\*    | Supabase project URL                                 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | frontend | yes\*    | Supabase anon (public) key                           |
| `ALLOW_MOCK_BUILD`              | frontend | no       | Explicit local/CI fixture build opt-in               |
| `SUPABASE_URL`                  | scraper  | yes      | Supabase project URL                                 |
| `SUPABASE_KEY`                  | scraper  | yes      | Service-role key (writes)                            |
| `FEC_API_KEY`                   | scraper  | no       | data.gov key for campaign-donor enrichment           |
| `OPENSTATES_API_KEY`            | scraper  | no       | OpenStates key for state roll-call votes             |
| `STATE_UNVERIFIED_ENRICHMENT_LIMIT` | scraper | no    | Bounded count of state profiles to enrich via LittleSis |
| `STATE_UNVERIFIED_ENRICHMENT_OFFSET` | scraper | no   | Zero-based start offset for rotating state LittleSis batches |
| `HOUSE_ROLL_CALL_WRITE_MODE`    | scraper  | no       | `disabled` by default; `enabled` opts into the separately DB-gated House RPC |
| `CURRENTS_API_KEY`              | scraper  | no       | News tier 1                                          |
| `NEWSDATA_API_KEY`              | scraper  | no       | News tier 2 (requires attribution)                   |
| `THENEWSAPI_KEY`                | scraper  | no       | News tier 3 credential                               |
| `THENEWSAPI_PRODUCTION_APPROVED` | scraper | no       | Set `true` only after terms/republication review     |

\* Local development can use mock fixtures when these are absent; static fixture builds
must explicitly set `ALLOW_MOCK_BUILD=true`. Production builds and runtime pages fail
visibly instead of presenting fixtures as live data. The news aggregator works with no
keys at all (it degrades to keyless GDELT URL discovery).

The official House Clerk roll-call extractor always fetches one bounded window for aggregate
reconciliation. `HOUSE_ROLL_CALL_WRITE_MODE=enabled` permits that same in-memory normalized
snapshot to call migration `0026`'s private atomic RPC only when listing, XML parsing, exact
Bioguide identity coverage, GovTrack reconciliation, and source health are all complete.
Overlapping listing pages fail closed, and parsed vote categories must exactly match the
Clerk XML's `totals-by-vote`. The database `production_writes_enabled` gate must also be
enabled separately. Both checked-in defaults remain disabled; either disabled gate prevents
writes, and this path never writes legacy `voting_records`. Do not enable either gate yet:
migration `0026` serializes each roll call but does not reject an older `fetched_at` observation.
A forward-only hardening migration must add that monotonic guard before production rollout.

Never commit secrets. `.env` and `.env.*` are gitignored (except `.env.example`). Templates
live in [`frontend/example.env`](frontend/example.env) and
[`scraper/example.env`](scraper/example.env).

---

## Deployment

Both pipelines run from GitHub Actions:

- **`.github/workflows/nextjs.yml`** — builds the static frontend and deploys it to GitHub
  Pages. Set `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` as repository
  secrets (embedded in the client bundle; the anon key is public by design, protected by
  Supabase RLS). The home/search, `/directory`, `/profile?id=<uuid>`, and profile spoke
  views read Supabase **live in the browser**, including contact, financial disclosures,
  campaign donors, voting records, media mentions, and connections. The legacy pretty
  `/[politician_id]` route availability is still tied to static generation, so brand-new
  rows should be linked through `/profile?id=<uuid>` until a deploy creates the SEO route.
  The deploy is wired to re-run automatically after a *successful* nightly ETL via a
  `workflow_run` trigger. (A failed scraper run does **not** trigger the deploy, so the live
  site keeps the last good build rather than shipping nothing.)
- **`.github/workflows/scraper.yml`** — runs the Python ETL on a nightly schedule, writing
  fresh data into Supabase.

### Interpreting ETL identity-health output

The scraper prints identity-health totals and includes them in `ETL_SUMMARY_JSON`.
For identity-resolution triage, focus on:

- `pending_identity_observer_candidates`: all pending identity candidates.
- `pending_identity_observer_blocked_candidates`: newly detected pending candidates blocked by
  deterministic conflicts (`identity_observer_blocked_*`).
- `pending_identity_observer_blocked_candidate_reasons`: map of blocked-pending candidate counts by
  reason suffix (for `identity_observer_blocked_<reason>`).
- `blocked_identity_observer_candidates`: candidates already reviewed and marked `blocked`, waiting for
  maintainer action.
- `blocked_identity_observer_candidate_reasons`: map of blocked review candidates by reason suffix.
- `pending_identity_observer_review_candidates`: pending non-conflict review work
  (`identity_observer_pending_*`, e.g. missing deterministic identity).
- `pending_openstates_federal_duplicate_candidates` / `approved_openstates_federal_duplicate_candidates`:
  queue and resolution state for OpenStates federal-legacy duplicates.
- `openstates_federal_legacy_profiles_total` / `openstates_federal_legacy_profiles_refreshed_this_run`:
  stale-legacy federal-like profile count and how many refreshed since the ETL started.

Quick triage:

- `pending_identity_observer_blocked_candidates > 0` means the latest run introduced fresh deterministic conflicts.
  Include `pending_identity_observer_blocked_candidate_reasons` to triage by reason.
- `blocked_identity_observer_candidates > 0` means existing maintainer-blocked conflicts are still waiting.
  Include `blocked_identity_observer_candidate_reasons` to see what needs review.

Optional maintainer SQL checks (run in the Supabase SQL editor):

```sql
-- Newest unresolved identity triage queue
select
  status,
  candidate_type,
  source_legacy_politician_id as source_legacy_id,
  candidate_legacy_politician_id as candidate_legacy_id,
  evidence
from identity_resolution_candidates
where status in ('pending', 'blocked')
  and candidate_type like 'identity_observer_%'
order by status, candidate_type, created_at desc
limit 200;
```

```sql
-- Top blocked-reason families waiting on maintainer action
select candidate_type, count(*) as cnt
from identity_resolution_candidates
where status = 'blocked'
  and candidate_type like 'identity_observer_%'
group by candidate_type
order by cnt desc;
```

### Applying migrations

There is **no migration runner**. Neither workflow applies SQL to Supabase — `scraper.yml`
only runs the ETL and `nextjs.yml` only builds.

- **Brand-new database:** run [`schema.sql`](schema.sql) once, then apply every numbered
  migration once in filename order. `schema.sql` deliberately refuses to run after the
  canonical `people` layer exists.
- **Existing database:** apply only the next unapplied numbered migration. Starting with
  migration `0022`, applied versions are recorded in `public.schema_migrations` and checked
  by scraper preflight.
- **`psql`:** run each migration with `--single-transaction` unless that migration explicitly
  documents different handling. This keeps temporary tables alive for the whole file and
  prevents half-applied data changes.

Do **not** replay the full historical migration directory against an upgraded database.
Some migrations contain guarded data decisions and review-state transitions, not just
idempotent DDL. In particular, replaying `0011` after the approved `0015` identity cleanup
can reconstruct stale mappings, while replaying the original `0016` seeds can overwrite
maintainer review state. Use a new forward repair migration instead of editing live history.

> **Symptom of un-applied migrations:** the scraper log fills with PGRST204 errors like
> `Could not find the 'district' column of 'politicians' in the schema cache`, and profile
> pages show stale/empty data. Recover in this order:
>
> 1. Apply the pending migrations (e.g. `0002`–`0007`) against the live database. If a
>    freshly-added column still isn't found right after, reload PostgREST's schema cache:
>    `NOTIFY pgrst, 'reload schema';`
> 2. **Run the Nightly ETL Scraper and confirm it succeeds** — look for `[+] Updated/Inserted
>    Hub` lines and **no** PGRST204 errors. This is the step that actually writes data; a
>    drifted run writes *nothing*.
> 3. Re-run **Deploy Next.js to GitHub Pages** so the profile pages re-bake. A successful
>    scraper run triggers this automatically, but you can run it manually too.
>
> Do **not** skip straight from step 1 to step 3: the deploy only bakes whatever is already
> in the database, so redeploying before a successful scrape just re-freezes the same
> stale/empty data.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Key rules for this repo:

1. **No paid APIs** — all scraper sources must be free-tier or open source.
2. **Label unconfirmed data** — third-party/unverified data must be visibly marked in the UI
   (the "Visual Firewall").
3. **Classification is data-first** — the directory should prefer normalized
   `government_level`, `government_branch`, `office_type`, and `jurisdiction` columns. The
   legacy keyword classifier is only a compatibility fallback; if you edit it, State/Federal
   rules must still sit above generic Local rules.
4. **Sign off every commit (DCO)** — append `--signoff` (`-s`) to every `git commit`.
5. **New work branches off `main`** and lands via PR; maintainers handle merges.

---

## License

See [`AUTHORS`](AUTHORS) for contributors. This repository is licensed under the
GNU General Public License v3.0. See [LICENSE](LICENSE).
