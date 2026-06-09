# Architecture

A high-level tour of how Avanguardia Publica is put together. The full
data-model shapes are in the [spec](../avanguardia-publica-spec.md);
this document is a working map of the codebase.

## Stack

| Layer    | Tech                                                        |
|----------|-------------------------------------------------------------|
| Database | PostgreSQL 16 (full-text search via `tsvector` + GIN)        |
| Cache    | Redis 7                                                     |
| Backend  | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Celery         |
| Frontend | React 19, Vite 6, TanStack Query, Tailwind, Recharts        |
| CI       | GitHub Actions: ruff + tsc/vite on PRs; Pages deploy on main |

## Repo layout

```
backend/
  app/
    api/routers/        FastAPI routers, one per resource
    core/               config, database, cache, auth, celery_app
    etl/                adapter framework + one module per source
    models/             SQLAlchemy models (one per table)
    schemas/            Pydantic request/response models
    main.py             FastAPI app + middleware + health endpoints
  alembic/              migrations (versions/, env.py, alembic.ini)
  tests/                pytest tests (currently a scaffold)
  Dockerfile            python:3.12-slim + uvicorn
  Procfile              web / worker / beat / release
frontend/
  src/
    api/                …                                       
    components/         reusable React components
    pages/              one file per route
    lib/                shared API client + utilities
  vite.config.ts        base: '/avanguardia-publica/' (project page)
  eslint.config.js      flat config for ESLint 9
.github/workflows/
  ci.yml                PR lint + build
  deploy.yml            build + GitHub Pages on main
```

## Data model

The unified schema lives in
[`backend/app/models/`](../backend/app/models). Key tables:

- `politician` — the canonical entity. Identified by
  `(source_name, source_record_id)` per source, with cross-source
  linkage via `bioguide_id`, `fec_ids`, `icpsr_id`, `voteview_id`,
  `opensecrets_id`. Phase 5 added `country_code` (ISO 3166-1 alpha-2)
  and `jurisdiction_level` (federal / state / provincial / territorial
  / municipal).
- `organization` — PACs, committees, lobbying firms, corporations.
- `contribution` — campaign donations; `source_name` is
  `fec_api` / `opensecrets_bulk` / (future) state campaign-finance sources.
- `voting_record` — one row per legislator per roll-call vote.
- `politician_ideology_score` — DW-NOMINATE per legislator per
  congress.
- `lobbying_record` — Senate LDA filings.
- `financial_disclosure` — STOCK Act and corporate Form 4 filings.
- `government_contract` — USAspending.gov awards.
- `politician_*` junction tables — resolve a contribution / lobbying
  record / contract back to a specific politician.
- `tag` and `politician_tag` — admin-defined labels.
- `source` — tracks ETL state (`last_synced_at`, `status`, `errors`).

Every ingested table has a `UNIQUE(source_name, source_record_id)`
constraint. **Always** dedup at the source-of-record level — never
rely on a nullable field like `fec_filing_id` (NULLs collide in
PostgreSQL).

Full-text search uses STORED `tsvector` columns with GIN indexes on
politician, organization, contribution, and voting_record, generated
from the underlying text fields. The columns are kept in sync by
PostgreSQL itself (no application-side triggers).

## ETL framework

Every data source is a `BaseSourceAdapter`
([`backend/app/etl/base.py`](../backend/app/etl/base.py)) that
implements three methods:

1. `fetch_records()` — call the source API or read a bulk file, return
   a list of raw dicts. Use safety caps on pagination.
2. `normalize(raw)` — map a raw record to the unified schema. Pure
   function, no DB access.
3. `_upsert(record, db)` — `INSERT … ON CONFLICT (source_name,
   source_record_id) DO UPDATE` so the same run is idempotent.

The base `run_sync()` opens **one** DB session for the whole batch,
processes records in a loop with a savepoint per record (so a single
bad row doesn't kill the batch), commits every 500 records, and
returns a `SyncResult` summary.

Adapters are registered in
[`backend/app/etl/tasks.py`](../backend/app/etl/tasks.py). To add a
new source: write the adapter, register it in `REGISTERED_SOURCES`
and the adapter dict, and add the source name to the admin health
`source_table_map`. See
[`DEVELOPING.md`](./DEVELOPING.md#adding-a-new-source-adapter) for a
walkthrough.

There are two ingestion styles:

- **Live API adapters** (`fec.py`, `congress_gov.py`, `senate_lda.py`,
  `house_clerk.py`, `usaspending.py`, `sec_edgar.py`, `quiver_quant.py`)
  call the upstream API each sync.
- **Bulk CSV adapters** (`opensecrets.py`, `canada_elections.py`,
  `ca_calaccess.py`) read pre-downloaded files from a local path
  specified by an env var. This is necessary when the source doesn't
  have a usable open API (Elections Canada, Cal-Access) or charges
  for the API but provides free bulk data (OpenSecrets).

## Caching

The politicians list endpoint is wrapped with a thin Redis cache
([`backend/app/core/cache.py`](../backend/app/core/cache.py)). The
decorator:

- Builds a cache key from a **callable** that receives the same
  query params as the endpoint, so `/politicians?page=2&state=CA`
  and `/politicians?page=1` get different cache slots.
- **Fails open**: if Redis is unreachable, the wrapped function
  executes as a normal uncached call. This means a downed Redis
  never causes a 5xx response — users just see slightly slower
  responses.

Currently only the politicians list is cached. The cache is
configured at a 60-second TTL because politician data churns
infrequently.

## API surface

| Path | Purpose | Auth |
|------|---------|------|
| `GET /api/health` | Liveness check | None |
| `GET /api/health/ready` | DB + Redis reachability | None |
| `GET /api/politicians` | Paginated list with filters | None |
| `GET /api/politicians/{id}` | Single politician | None |
| `GET /api/politicians/{id}/{voting,contributions,financials,contracts}` | Per-resource | None |
| `GET /api/organizations`, `/api/organizations/{id}`, `/api/organizations/{id}/flow` | PACs, firms, "follow the money" | None |
| `GET /api/search` | Cross-entity full-text search | None |
| `GET /api/admin/sources` | Per-source health snapshot | `X-Admin-Key` header |
| `GET/POST/PATCH/DELETE /api/admin/tags` | Tag CRUD | `X-Admin-Key` |
| `GET /api/admin/politicians/{id}/tags` | List a politician's tags | None (admin-only tags filtered out) |
| `PUT/DELETE /api/admin/politicians/{id}/tags/{tag_id}` | Attach / detach | `X-Admin-Key` |

OpenAPI docs at `/docs` and `/redoc` are auto-generated from the
Pydantic schemas.

## Frontend

Single-page React app with React Router. Three pages (HomePage,
PoliticianPage, OrganizationPage) plus three feature pages
(SearchPage, AdminSourcesPage, organization profile) added across
Phases 4 and 5.

State management is **TanStack Query** for everything server-fetched —
no Redux, no Zustand. Each query has a stable key
(`['politician', id]`, `['politicians', { page, state, search }]`,
etc.) and a `staleTime` of 30 seconds for the search bar, default
otherwise. The `SearchBar` debounces input by 250ms so we don't fire
8 DB queries per keystroke.

Styling is **Tailwind 3** with a mobile-first responsive pass: the
header stacks on small screens, the politician grid collapses to one
column under `sm:`, and pagination goes full-width on mobile.

Vite is configured for GitHub Pages with
`base: '/avanguardia-publica/'` in `vite.config.ts`. Don't change
this without re-reading the deploy section in
[`DEPLOYMENT.md`](./DEPLOYMENT.md).

## What's intentionally out of scope

- **No authentication for public users.** The site is read-only.
  Admin endpoints use a single shared secret.
- **No real-time updates.** All data is refreshed on a Celery beat
  schedule (daily). The frontend just refetches when the user
  navigates.
- **No SSR.** The frontend is a static SPA hosted on GitHub Pages.
  SEO is not a concern for this project.
- **No state legislator voting records.** Most states don't publish
  roll-call votes in machine-readable form. See
  [`STATE_DATA_SOURCES.md`](../STATE_DATA_SOURCES.md) for the
  planned next sources.
