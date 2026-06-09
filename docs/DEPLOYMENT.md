# Deployment

The frontend and backend deploy independently. The frontend is a
static SPA on GitHub Pages; the backend is a FastAPI service plus
two Celery processes on a PaaS (Railway, Fly.io, Render, etc.).

## Table of contents

- [GitHub Pages (frontend)](#github-pages-frontend)
- [Backend (Railway / Fly / Render)](#backend-railway--fly--render)
- [One-time setup checklist](#one-time-setup-checklist)

---

## GitHub Pages (frontend)

`.github/workflows/deploy.yml` builds the frontend on every push to
`main` that touches `frontend/**`, then publishes the static build
to GitHub Pages.

### One-time setup: enable GitHub Pages

GitHub Pages must be enabled manually in the repository settings.
**This cannot be done from a workflow** — a repo admin has to do it
in the browser:

1. Open `https://github.com/<owner>/<repo>/settings/pages`
2. Under **Source**, select **GitHub Actions** (not "Deploy from a
   branch"). Save.

That's the only thing standing between a successful deploy and a
`404 — Failed to create deployment`. The full error from a
misconfigured repo is:

```
Error: Creating Pages deployment failed
Error: HttpError: Not Found
    at createPagesDeployment (...)
Ensure GitHub Pages has been enabled:
https://github.com/<owner>/<repo>/settings/pages
```

Once enabled, the next push to `main` will deploy to
`https://<owner>.github.io/<repo>/`.

The workflow uses
[`actions/deploy-pages@v4`](https://github.com/actions/deploy-pages),
which requires:

- `permissions: pages: write` ✅ (already in the workflow)
- `permissions: id-token: write` ✅ (already in the workflow, for OIDC)
- An `actions/upload-pages-artifact@v3` step that produces a Pages-compatible
  artifact ✅ (already in the workflow, pointing at `frontend/dist`)

### What the workflow does

1. Checks out the repo at the pushed commit.
2. Sets up Node 20.
3. `npm install` (production deps + dev deps for the build).
4. `npm run build`, which runs `tsc -b && vite build`. The build
   output goes to `frontend/dist`.
5. `actions/upload-pages-artifact@v3` uploads the artifact.
6. `actions/deploy-pages@v4` asks the GitHub API to create a
   deployment for the artifact.

### Environment variables

The workflow hardcodes the API URL to
`https://api.avanguardapublica.com` via the `VITE_API_URL` env var
on the `npm install` and `npm run build` steps. If you point the
frontend at a different backend, edit those two lines.

### CORS

The backend must allow the Pages origin. The default
`CORS_ORIGINS` env var in `backend/.env.example` is:

```
https://zdoss.github.io,http://localhost:5173
```

`zdoss.github.io` covers the project page. If the repo is renamed or
moved to a different org, update this.

### Vite base path

`frontend/vite.config.ts` has `base: '/avanguardia-publica/'`. This
matches the GitHub Pages URL `https://zdoss.github.io/avanguardia-publica/`.
If you fork the repo, change the `base` to match the new repo name.

---

## Backend (Railway / Fly / Render)

The `Procfile` declares four processes:

```
release: alembic -c alembic/alembic.ini upgrade head
web:     uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker:  celery -A app.core.celery_app worker --loglevel=info
beat:    celery -A app.core.celery_app beat --loglevel=info
```

### Railway

Railway reads the `Procfile` automatically. Setup:

1. Create a new Railway project, link this repo.
2. Add a Postgres 16 service. Copy its connection string to
   `DATABASE_URL` on the backend service.
3. Add a Redis 7 service. Copy its URL to `REDIS_URL`.
4. Deploy the backend. Railway will run `release` (alembic upgrade)
   then start `web`. Add the `worker` and `beat` processes via
   "Add Service → Empty Service" and point them at the same repo
   with the appropriate Procfile process selected.
5. Set the env vars from [`backend/.env.example`](../backend/.env.example).
   All API keys are optional at the infrastructure level — without
   them, only the sources that don't need keys will sync.

### Fly.io

The `Dockerfile` is the entrypoint. `fly launch` then `fly deploy`
with a `fly.toml` that declares the four processes. (One for each
Procfile line.)

### Render

Render reads the `Procfile` natively. Create a Web Service for
`web`, a Background Worker for `worker`, and a Cron Job (or
separate worker) for `beat`.

### Required env vars (production)

| Var | Required? | Notes |
|-----|-----------|-------|
| `DATABASE_URL` | ✅ | `postgresql://...` |
| `REDIS_URL` | ✅ | `redis://...` |
| `CORS_ORIGINS` | ✅ | Comma-separated, include the Pages origin |
| `ADMIN_API_KEY` | ✅ in prod | Long random string; gates `/api/admin/*` |
| `API_KEY_DATA_GOV` | ⚠️ recommended | Needed for `fec_api` and `congress_gov_api` |
| `SENATE_LDA_API_KEY` | Optional | Needed for `senate_lda` |
| `QUIVER_QUANT_API_KEY` | Optional | Needed for `quiver_quant` |
| `OPENSECRETS_BULK_PATH` | Optional | Path to OpenSecrets CSV bundle |
| `CANADA_ELECTIONS_BULK_PATH` | Optional | Path to Elections Canada CSVs |
| `CA_CALACCESS_BULK_PATH` | Optional | Path to Cal-Access `Cover_Page_Cd.csv` |
| `SEC_EDGAR_USER_AGENT` | Optional | Real contact email (SEC fair-access policy) |

### Health checks

`GET /api/health` is the liveness check. `GET /api/health/ready`
verifies DB and Redis are reachable. Use the former for
`/healthcheck`, the latter for a startup probe if the PaaS supports
it.

### Database migrations

The `release` process in the Procfile runs `alembic upgrade head`
on every deploy. This is idempotent and safe to run repeatedly. If
a migration fails, Railway/Render will mark the deploy as failed
and the previous version stays running.

To apply a migration manually:

```bash
# Railway: railway run alembic upgrade head
# Fly.io:  fly ssh console -C "alembic upgrade head"
# Render:  open the service Shell tab and run: alembic upgrade head
```

To roll back:

```bash
alembic downgrade -1
```

---

## One-time setup checklist

If you're forking or starting from scratch, do these in order:

- [ ] **GitHub**: enable Pages on the repo
  (`Settings → Pages → Source: GitHub Actions`).
- [ ] **GitHub**: protect `main` (Settings → Branches → Add rule →
  require PR + 1 review + status checks).
- [ ] **PaaS**: provision Postgres 16 and Redis 7.
- [ ] **PaaS**: create the four backend processes (`release`, `web`,
  `worker`, `beat`) with the Procfile.
- [ ] **PaaS**: set the env vars from
  `backend/.env.example`. Generate a strong `ADMIN_API_KEY`.
- [ ] **DNS**: if you have a custom domain, set the `CNAME` for
  `api.avanguardapublica.com` (or whatever) to the PaaS endpoint,
  and update `VITE_API_URL` in the deploy workflow to match.
- [ ] **DNS**: configure the GitHub Pages custom domain (Settings →
  Pages → Custom domain). Update `vite.config.ts` `base` if you
  move off the project page.
- [ ] **Secrets**: register for the source API keys you want
  (data.gov, Senate LDA, Quiver Quant) and put them in the PaaS
  env. OpenSecrets requires a separate approval.
- [ ] **First sync**: trigger `etl.sync_all_sources` from a worker
  shell. Verify each source's `last_synced_at` updates and
  `/admin/sources` shows non-zero `total_records`.
