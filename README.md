# Avanguardia Publica

> The unvarnished public record index.

Avanguardia Publica is a public-facing political-data transparency tool. It aggregates,
classifies, and displays publicly available information about U.S. politicians across the
Federal, State, and Local levels, presenting it as a clean, read-only encyclopedia.

The project follows a **decoupled, zero-cost architecture**: a Python ETL pipeline pushes
data into Supabase on a schedule, and a statically-exported Next.js frontend reads from it.
The render model is **hybrid** — the home/search and `/directory` pages query Supabase
**live in the browser**, while the `/[politician_id]` profile pages are **baked at build
time** (their contact / financial / donor / voting / media tabs only refresh when the
frontend is redeployed; the profile's Connections tab is the one live exception). Read
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
| Frontend     | Next.js (App Router) + React 19 + Tailwind CSS 4 | `output: 'export'` — hybrid: home/search + `/directory` read live; profile pages baked at build time |
| Hosting      | GitHub Pages (frontend) + GitHub Actions (ETL)   | Zero-cost                                           |

See [`spec.md`](spec.md) for the full product/technical spec and [`AGENTS.md`](AGENTS.md)
for architecture handoff notes.

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

- **Node.js** 20+ and npm (frontend)
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

### 2. Scraper

```bash
cd scraper
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure environment (see scraper/example.env)
cp example.env .env
#   Fill in SUPABASE_URL, SUPABASE_KEY (service role), and any data-source API keys

python main.py
```

All scraper data sources are **free-tier or open-source** (no paid APIs). The news
aggregator uses a multi-tier circuit-breaker strategy (Currents → NewsData.io →
TheNewsAPI → GDELT) so it degrades gracefully under rate limits.

---

## Environment variables

| Variable                        | Used by  | Required | Purpose                                              |
| ------------------------------- | -------- | -------- | ---------------------------------------------------- |
| `NEXT_PUBLIC_SUPABASE_URL`      | frontend | yes\*    | Supabase project URL                                 |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | frontend | yes\*    | Supabase anon (public) key                           |
| `SUPABASE_URL`                  | scraper  | yes      | Supabase project URL                                 |
| `SUPABASE_KEY`                  | scraper  | yes      | Service-role key (writes)                            |
| `FEC_API_KEY`                   | scraper  | no       | data.gov key for campaign-donor enrichment           |
| `CURRENTS_API_KEY`              | scraper  | no       | News tier 1                                          |
| `NEWSDATA_API_KEY`              | scraper  | no       | News tier 2 (requires attribution)                   |
| `THENEWSAPI_KEY`                | scraper  | no       | News tier 3                                          |

\* Without them the frontend falls back to mock data. The news aggregator works with no keys
at all (it degrades to the keyless GDELT fallback).

Never commit secrets. `.env` and `.env.*` are gitignored (except `.env.example`). Templates
live in [`frontend/example.env`](frontend/example.env) and
[`scraper/example.env`](scraper/example.env).

---

## Deployment

Both pipelines run from GitHub Actions:

- **`.github/workflows/nextjs.yml`** — builds the static frontend and deploys it to GitHub
  Pages. Set `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` as repository
  secrets (embedded in the client bundle; the anon key is public by design, protected by
  Supabase RLS). The home/search and `/directory` pages read Supabase **live in the
  browser**, but the **`/[politician_id]` profile pages are baked at build time** — their
  contact / financial / donor / voting / media tabs only refresh when this deploy re-runs.
  It is wired to re-run automatically after a *successful* nightly ETL via a `workflow_run`
  trigger, so profiles re-bake after each scrape. (A failed scraper run does **not** trigger
  the deploy, so the live site keeps the last good build rather than shipping nothing.)
- **`.github/workflows/scraper.yml`** — runs the Python ETL on a nightly schedule, writing
  fresh data into Supabase.

### Applying migrations

There is **no migration runner**. Neither workflow applies SQL to Supabase — `scraper.yml`
only runs the ETL and `nextjs.yml` only builds. After adding or changing anything in
[`migrations/`](migrations/), apply it manually in the **Supabase SQL editor** (or via `psql`),
in filename order. All migrations are idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE … IF NOT
EXISTS`, `DROP POLICY IF EXISTS`), so re-running the full set is safe.

> **Symptom of un-applied migrations:** the scraper log fills with PGRST204 errors like
> `Could not find the 'district' column of 'politicians' in the schema cache`, and profile
> pages show stale/empty data. The fix is to run the pending migrations (e.g. `0002`–`0004`)
> against the live database, then re-run the **Deploy Next.js to GitHub Pages** workflow so
> the profile pages re-bake. If a freshly-added column still isn't found right after applying,
> reload PostgREST's schema cache (`NOTIFY pgrst, 'reload schema';`).

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Key rules for this repo:

1. **No paid APIs** — all scraper sources must be free-tier or open source.
2. **Label unconfirmed data** — third-party/unverified data must be visibly marked in the UI
   (the "Visual Firewall").
3. **Classifier order matters** — in `DirectoryClient.tsx`, rules are evaluated top-to-bottom
   and first match wins; State/Federal rules must sit above generic Local rules.
4. **Sign off every commit (DCO)** — append `--signoff` (`-s`) to every `git commit`.
5. **New work branches off `main`** and lands via PR; maintainers handle merges.

---

## License

See [`AUTHORS`](AUTHORS) for contributors. Add a `LICENSE` file before public distribution.
