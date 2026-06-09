# Backend

FastAPI service, SQLAlchemy 2 models, Alembic migrations, and Celery
ETL workers. Python 3.12+.

See [`/docs/USAGE.md`](../docs/USAGE.md) for the end-to-end
operator guide and [`/docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
for the high-level data model / ETL design.

## Quick start

```bash
# From the repo root
docker compose up -d db redis

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env to fill in API keys.

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The API is on `http://localhost:8000`. OpenAPI at `/docs`.

In a second terminal:

```bash
celery -A app.core.celery_app worker -Q avanguardia -l info
```

## Project layout

```
backend/
  app/
    main.py              FastAPI app, middleware, /api/health*
    api/routers/         one router per resource
    core/
      config.py          pydantic-settings (env vars)
      database.py        SQLAlchemy engine + SessionLocal
      celery_app.py      Celery instance + beat schedule
      cache.py           Redis cache decorator
      auth.py            X-Admin-Key header dependency
    etl/
      base.py            BaseSourceAdapter + run_sync()
      fec.py             FEC API
      congress_gov.py    Congress.gov API
      voteview.py        VoteView bulk import
      opensecrets.py     OpenSecrets bulk CSV
      senate_lda.py      Senate LDA REST API
      house_clerk.py     House Clerk STOCK Act ZIP
      usaspending.py     USAspending.gov POST API
      sec_edgar.py       SEC EDGAR Form 4 form.idx
      quiver_quant.py    Quiver Quant API
      canada_elections.py  Elections Canada CSV
      ca_calaccess.py    California Cal-Access CSV
      tasks.py           Celery task registration
    models/              one SQLAlchemy model per table
    schemas/             Pydantic request/response models
  alembic/
    alembic.ini
    env.py
    versions/            one .py per migration
  tests/                 pytest tests (scaffold; add real tests here)
  Dockerfile             python:3.12-slim + uvicorn
  Procfile               release / web / worker / beat
  pyproject.toml         deps + ruff config
```

## Common tasks

### Add a migration

```bash
alembic revision --autogenerate -m "describe change"
# Review the generated file in alembic/versions/, then:
alembic upgrade head
```

See [`/docs/DEVELOPING.md`](../docs/DEVELOPING.md#extending-the-schema)
for the full pattern, including the nullable→backfill→NOT NULL
trick.

### Trigger an ETL sync

```bash
# Single source
celery -A app.core.celery_app call etl.sync_source \
  --kwargs='{"source_name": "fec_api"}'

# All sources
celery -A app.core.celery_app call etl.sync_all_sources
```

### Add a new API endpoint

See [`/docs/DEVELOPING.md`](../docs/DEVELOPING.md#adding-an-api-endpoint).

### Lint

```bash
ruff check .
```

The CI runs the same command (`.github/workflows/ci.yml`).

### Tests

```bash
pytest
```

The `tests/` directory is currently a scaffold — add real tests
under `tests/{module}/test_{resource}.py` as you add features.

## Environment variables

See [`.env.example`](./.env.example) for the full list and defaults.
The most important ones:

| Var | Required? | Notes |
|-----|-----------|-------|
| `DATABASE_URL` | ✅ | `postgresql://...` |
| `REDIS_URL` | ✅ | `redis://...` |
| `CORS_ORIGINS` | ✅ | Comma-separated origins |
| `ADMIN_API_KEY` | ✅ in prod | Long random string; gates `/api/admin/*` |
| `API_KEY_DATA_GOV` | ⚠️ | Needed for FEC and Congress.gov |
| `SENATE_LDA_API_KEY` | Optional | Needed for Senate LDA |
| `QUIVER_QUANT_API_KEY` | Optional | Needed for Quiver Quant |
| `OPENSECRETS_BULK_PATH` | Optional | Local path to OpenSecrets CSVs |
| `CANADA_ELECTIONS_BULK_PATH` | Optional | Local path to Elections Canada CSVs |
| `CA_CALACCESS_BULK_PATH` | Optional | Local path to Cal-Access CSVs |
| `SEC_EDGAR_USER_AGENT` | Optional | Real contact email (SEC fair-access) |

## Database

PostgreSQL 16. All migrations live under
[`alembic/versions/`](./alembic/versions/). The base `release`
process in the `Procfile` runs `alembic upgrade head` on every
deploy.

Every ingested table has a `UNIQUE(source_name, source_record_id)`
constraint for source-of-record dedup. **Always** use that pair as
the unique key; never rely on a nullable field (NULLs collide in
PostgreSQL).

## API surface

See [`/docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#api-surface)
for the full table. Auto-generated OpenAPI is at `/docs` and
`/redoc` when the server is running.

## Celery

The Celery instance lives in
[`app/core/celery_app.py`](./app/core/celery_app.py). Default
schedule:

- `etl.sync_all_sources` — daily at 04:00 UTC, via Celery beat.

The worker subscribes to the `avanguardia` queue. To run a one-off
task without beat:

```bash
celery -A app.core.celery_app call etl.sync_all_sources
```

See [`/docs/ADMIN.md`](../docs/ADMIN.md) for the source-health
dashboard and what the worker writes back to the `source` table.
