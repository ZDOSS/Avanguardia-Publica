# Usage

How to operate Avanguardia Publica — running it locally for development,
triggering ETL syncs, and pointing a production deployment at it.

> Looking for a more in-depth tour? See
> [`ARCHITECTURE.md`](./ARCHITECTURE.md). Looking to extend the app?
> See [`DEVELOPING.md`](./DEVELOPING.md).

## Table of contents

- [Local development with Docker Compose](#local-development-with-docker-compose)
- [Local development without Docker](#local-development-without-docker)
- [Triggering an ETL sync](#triggering-an-etl-sync)
- [Resetting the database](#resetting-the-database)
- [Smoke testing the API](#smoke-testing-the-api)
- [Production deployment](#production-deployment)

---

## Local development with Docker Compose

The fastest path. Brings up Postgres, Redis, the API, a Celery worker,
and a Celery beat scheduler with one command.

```bash
# 1. Clone
git clone https://github.com/ZDOSS/Avanguardia-Publica.git
cd Avanguardia-Publica

# 2. (Optional) Create a top-level .env with API keys
cat > .env <<'EOF'
API_KEY_DATA_GOV=your_data_gov_key_here
SENATE_LDA_API_KEY=your_senate_lda_key_here
QUIVER_QUANT_API_KEY=your_quiver_quant_key_here
ADMIN_API_KEY=any-shared-secret-for-admin-endpoints
EOF

# 3. Bring everything up
docker compose up --build
```

The compose file exposes:

| Service  | Port  | URL                          |
|----------|-------|------------------------------|
| postgres | 5432  | `postgresql://avanguardia:avanguardia@localhost:5432/avanguardia` |
| redis    | 6379  | `redis://localhost:6379/0`   |
| backend  | 8000  | `http://localhost:8000`      |
| frontend | 5173  | (not in compose — see below) |

The backend's Dockerfile runs `alembic upgrade head` on container start,
so the schema is always current.

To run the frontend in dev mode alongside the compose stack:

```bash
cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev
# → http://localhost:5173
```

## Local development without Docker

Useful if you have Postgres + Redis running natively or want tighter
edit-rebuild loops.

### Prerequisites

- Python 3.12+
- Node 20+
- PostgreSQL 16
- Redis 7

### 1. Start Postgres and Redis

```bash
# macOS (Homebrew)
brew services start postgresql@16
brew services start redis

# Linux (Debian/Ubuntu)
sudo systemctl start postgresql redis
```

Create the database:

```bash
psql -U postgres <<'SQL'
CREATE USER avanguardia WITH PASSWORD 'avanguardia';
CREATE DATABASE avanguardia OWNER avanguardia;
GRANT ALL PRIVILEGES ON DATABASE avanguardia TO avanguardia;
SQL
```

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env to point at your local Postgres / Redis and fill in API keys.

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The FastAPI dev server is now on `http://localhost:8000`. Interactive
docs at `http://localhost:8000/docs`.

### 3. Celery worker (separate terminal)

```bash
cd backend && source .venv/bin/activate
celery -A app.core.celery_app worker -Q avanguardia -l info
```

### 4. Celery beat (separate terminal, optional)

The beat scheduler is what triggers the daily "sync all sources" job.
Skip this in dev if you only want manual syncs.

```bash
cd backend && source .venv/bin/activate
celery -A app.core.celery_app beat -l info
```

### 5. Frontend

```bash
cd frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev
# → http://localhost:5173
```

The Vite dev server proxies no paths by default; it talks to
`VITE_API_URL` directly. Make sure the backend is up before loading
data-heavy pages or they'll 500.

## Triggering an ETL sync

The Celery worker pulls jobs from the `avanguardia` queue. To trigger
a sync manually:

```bash
# All sources
docker compose exec backend celery -A app.core.celery_app call etl.sync_all_sources

# A single source
docker compose exec backend celery -A app.core.celery_app call etl.sync_source --kwargs='{"source_name": "fec_api"}'

# Without docker (assuming worker is running)
cd backend && source .venv/bin/activate
python -c "
from app.etl.tasks import sync_source
sync_source.delay('fec_api')
"
```

The registered source names are listed in
[`REGISTERED_SOURCES`](../backend/app/etl/tasks.py):

```
fec_api, congress_gov_api, voteview, opensecrets_bulk,
senate_lda, house_clerk, usaspending, sec_edgar, quiver_quant,
canada_elections, ca_calaccess
```

Each source's progress is visible on the admin Sources dashboard at
`/admin/sources`.

## Resetting the database

Wipe everything and re-run all migrations:

```bash
docker compose down -v                # drops the postgres volume
docker compose up -d db
docker compose up backend             # runs alembic upgrade head on start
```

To keep the schema but clear all data:

```bash
docker compose exec db psql -U avanguardia -d avanguardia -c "
TRUNCATE
  contribution, voting_record, politician_ideology_score,
  lobbying_record, financial_disclosure, government_contract,
  organization, politician, politician_contribution,
  politician_lobbying_record, politician_government_contract,
  politician_tag, source
RESTART IDENTITY CASCADE;
"
```

## Smoke testing the API

The backend ships with interactive OpenAPI docs at
`http://localhost:8000/docs` (Swagger UI) and
`http://localhost:8000/redoc`.

Quick curl checks:

```bash
# Health
curl http://localhost:8000/api/health

# Readiness (verifies DB and Redis)
curl http://localhost:8000/api/health/ready

# List politicians, first page, US only
curl 'http://localhost:8000/api/politicians?country_code=US&per_page=5'

# Cross-entity full-text search
curl 'http://localhost:8000/api/search?q=climate&limit=5'

# Admin source health (requires X-Admin-Key)
curl -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost:8000/api/admin/sources
```

## Production deployment

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full guide. The TL;DR:

- **Backend** runs as four Railway/Fly processes: `release` (alembic
  upgrade), `web` (uvicorn), `worker` (celery worker), `beat` (celery
  scheduler). The `Procfile` defines them.
- **Frontend** is built with `vite build` and deployed to GitHub Pages
  by `.github/workflows/deploy.yml` on every push to `main` that
  touches `frontend/**`.
- **CORS** must be set via the `CORS_ORIGINS` env var on the backend to
  include the GitHub Pages origin (default:
  `https://zdoss.github.io,http://localhost:5173`).
- **GitHub Pages must be enabled once** in the repo Settings → Pages
  page (Source: "GitHub Actions"). The deploy workflow cannot do this
  for you.
