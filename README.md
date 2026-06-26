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

### Applying migrations

There is **no migration runner**. Neither workflow applies SQL to Supabase — `scraper.yml`
only runs the ETL and `nextjs.yml` only builds. After adding or changing anything in
[`migrations/`](migrations/), apply it manually in the **Supabase SQL editor** (or via `psql`),
in filename order. All migrations are idempotent (`ADD COLUMN IF NOT EXISTS`, `CREATE … IF NOT
EXISTS`, `DROP POLICY IF EXISTS`), so re-running the full set is safe.

> **Symptom of un-applied migrations:** the scraper log fills with PGRST204 errors like
> `Could not find the 'district' column of 'politicians' in the schema cache`, and profile
> pages show stale/empty data. Recover in this order:
>
> 1. Apply the pending migrations (e.g. `0002`–`0006`) against the live database. If a
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

See [`AUTHORS`](AUTHORS) for contributors. Add a `LICENSE` file before public distribution.
