# Avanguardia Publica

A public-facing political data transparency tool that aggregates structured data on US federal and (incrementally) state-level politicians across four domains:

1. **Campaign donors** — contributions, PACs, committees
2. **Policy positions** — voting records, ideology scores
3. **Outside paid engagements** — lobbying records, financial disclosures
4. **Businesses & investments** — stock trades, government contracts

The site is read-only for the public. Every data point shows its source
and last-synced date, and data from non-government sources carries a
disclaimer. No login required.

See [`avanguardia-publica-spec.md`](./avanguardia-publica-spec.md) for
the full product specification.

## What's in this repository

```
.
├── avanguardia-publica-spec.md    # the project spec
├── STATE_DATA_SOURCES.md          # state / international data source catalog
├── docker-compose.yml             # local dev: postgres + redis + backend + workers
├── AGENTS.md                      # working rules for AI agents / contributors
├── backend/                       # FastAPI + SQLAlchemy + Celery ETL
├── frontend/                      # React + Vite SPA
└── .github/workflows/             # CI + Pages deploy
```

## Quick start (local development)

The full step-by-step is in [`docs/USAGE.md`](./docs/USAGE.md). The
short version:

```bash
# 1. Start postgres + redis
docker compose up -d db redis

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env       # fill in API keys as needed
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3. Worker (separate terminal)
celery -A app.core.celery_app worker -Q avanguardia -l info

# 4. Frontend (separate terminal)
cd ../frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev
# → http://localhost:5173
```

## Documentation

- **[`docs/USAGE.md`](./docs/USAGE.md)** — operate the app end-to-end:
  running locally, triggering ETL syncs, deploying to production.
- **[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)** — data model
  summary, ETL framework, caching, frontend state management.
- **[`docs/DEVELOPING.md`](./docs/DEVELOPING.md)** — adding a new source
  adapter, extending the schema, adding an API endpoint or React page.
- **[`docs/ADMIN.md`](./docs/ADMIN.md)** — admin endpoints, source
  health dashboard, tag management, auth.
- **[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)** — production
  deployment: GitHub Pages for the frontend, Railway/Fly/Render for
  the backend, and the one-time GitHub Pages setup the repo currently
  needs.
- **[`backend/README.md`](./backend/README.md)** — backend-specific
  details (Alembic, Celery tasks, environment variables).
- **[`frontend/README.md`](./frontend/README.md)** — frontend-specific
  details (Vite config, env vars, lint/build).

## Phased roadmap

All five phases from the spec are merged:

- [x] Phase 1 — Foundation
- [x] Phase 2 — Richer data (VoteView, OpenSecrets, FEC campaign finance)
- [x] Phase 3 — Financial & influence (LDA, House Clerk, USAspending,
  SEC EDGAR, Quiver Quant)
- [x] Phase 4 — Polish & search (full-text search, admin tools, Redis
  cache, mobile responsive)
- [x] Phase 5 — State-level & international (country/jurisdiction
  abstraction, Canada Elections, California Cal-Access)

## License

GNU GPL v3.0 — see [`LICENSE`](./LICENSE).
