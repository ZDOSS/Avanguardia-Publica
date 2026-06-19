# Avanguardia Publica

> The unvarnished public record index.

Avanguardia Publica is a public-facing political-data transparency tool. It aggregates,
classifies, and displays publicly available information about U.S. politicians across the
Federal, State, and Local levels, presenting it as a clean, read-only encyclopedia.

The project follows a **decoupled, zero-cost architecture**: a Python ETL pipeline pushes
data into Supabase on a schedule, and a statically-exported Next.js frontend reads from it
**live in the browser** at runtime (the static export is the page shells/hosting — the data
is not baked into the build). See [`AGENTS.md`](AGENTS.md) → "Data flow".

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
| Frontend     | Next.js (App Router) + React 19 + Tailwind CSS 4 | `output: 'export'` — static shells; data read live from Supabase in the browser |
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
  secrets. These `NEXT_PUBLIC_*` values are embedded in the client bundle, so the exported
  pages read data **live from Supabase in the browser** (the anon key is public by design,
  protected by Supabase RLS); the build also uses them to enumerate static routes. The
  deploy ships the UI, not a data snapshot — content refreshes without a rebuild as the
  nightly ETL updates Supabase.
- **`.github/workflows/scraper.yml`** — runs the Python ETL on a nightly schedule, writing
  fresh data into Supabase.

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
