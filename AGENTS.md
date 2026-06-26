# AGENTS.md (Handoff Notes)

Welcome to the Avanguardia-Publica project! This document outlines the current state of the application, architecture, and critical guidelines for future development.

## 📌 Project Overview
Avanguardia-Publica is an application designed to aggregate, classify, and display public data and news articles about U.S. politicians across Federal, State, and Local governments. 

## 🏗️ Architecture & Stack
- **Frontend**: Next.js (React), Tailwind CSS, Lucide Icons.
- **Backend & Data**: Supabase (PostgreSQL).
- **Scraper Pipeline**: Python.
  - The pipeline uses a robust, highly-resilient multi-tier strategy for pulling news data.
  - Tiers: Currents API → NewsData.io → TheNewsAPI → GDELT (via `newspaper3k`).

### 🔑 Render model: STATIC EXPORT with LIVE client data
This is the single most-misread part of the architecture and it has burned multiple sessions.
Read it before touching any page or data-fetching code, and DO NOT "correct" it from intuition —
verify against the actual component (`"use client"` vs `async` server component).

`output: "export"` (in `next.config.ts`) emits a fully static site for GitHub Pages — **there is
no server at runtime.** Whether a given piece of data is live or frozen depends entirely on
*where the fetch runs*:

**LIVE — fetched in the user's browser at runtime; reflects the database with no rebuild:**
- `/` (home + search) — `app/page.tsx` is a `"use client"` component; fetches a small
  featured slice with `fetchPoliticianSummaries` and runs indexed full-text search via
  `searchPoliticians` (`lib/politicians.ts`) from `useEffect`.
- `/directory` — `app/directory/DirectoryClient.tsx` is `"use client"`.
- `/profile?id=<uuid>` — `app/profile/ProfilePageClient.tsx` is `"use client"` and fetches
  the profile header from `lib/profile.ts`.
- Profile data spokes under `app/[politician_id]/` are client-fetched independently:
  **Official Contact**, **Financial Disclosures**, **Campaign Donors**, **Voting Record**,
  **Connections**, and **Media**. Connections uses Postgres RPC (`lib/connections.ts`);
  the other spokes use focused Supabase helpers in `frontend/src/lib/`.

**BAKED — fetched once during `npm run build` and frozen into static HTML; changes ONLY when the
frontend is rebuilt/redeployed, NOT when the database changes:**
- The legacy pretty `/[politician_id]` route list is still enumerated by
  `generateStaticParams()` during `npm run build`, because GitHub Pages cannot create new
  dynamic routes at runtime. Its server component now fetches only the minimal profile header
  needed for the static shell; the contact card and profile tabs fetch live in the browser.

**The consequence:** after the nightly scraper writes new data, search and directory can link to
`/profile?id=<uuid>` immediately, and that live route can show the row without a frontend
rebuild. The legacy pretty `/[politician_id]` SEO route for a brand-new row still appears only
after a deploy, but its data spokes are live once the page exists.

**If you add a profile data view that must update without a rebuild,** make it a `"use client"`
component that queries Supabase directly, or add a Postgres **RPC** (`SECURITY DEFINER`,
`GRANT EXECUTE ... TO anon`) and call it with `supabase.rpc()` when computed server-side SQL is
needed.

## ✅ Recent Milestones (PR #20 merged)
The most recent major feature update was the completion of the Directory and News Aggregator overhaul. The following is now live on `main`:
1. **Interactive Directory (`/directory`)**
   - Client-side rendered directly from Supabase, featuring a 3-level collapsible accordion (Branch → Section → Sub-category).
   - Offices are correctly bucketed via keyword classification. Federal offices correctly take precedence over generic local ones (e.g., "county").
   - Full party filtering capabilities and a text-based search are fully functional.
2. **Multi-Tier News Aggregator**
   - The original WorldNews API was dropped in favor of free-tier services. The old `worldnews.py` extractor has been explicitly deleted.
   - A custom circuit breaker pattern was built (`news_aggregator.py`). It rotates to fallback APIs smoothly on `429 Too Many Requests`, `401 Unauthorized`, `500 Server Error`, or quota exhaustion.
   - Importantly, it correctly avoids cascading to lower tiers if an API simply returns no results (empty list). 
   - Uses an entirely free, keyless fallback to the open-source GDELT project (GKG TSV archives) combined with `newspaper3k` to scrape raw text, heavily protected by a 15-minute TTL cache to respect their servers.
3. **Robust Error Boundaries**
   - `[politician_id]/page.tsx` now properly throws database errors to yield a `500 Internal Server Error` instead of hiding behind a `404 Not Found` (which protected the app from aggressive SEO de-indexing during temporary database drops).

## ⚠️ Critical Development Guidelines
When contributing to this project, you must adhere strictly to these rules:

1. **No Paid APIs:** All scraper data sources must be free-tier or open source. Do not rely on paid subscriptions for indices.
2. **Data Integrity & Labeling:** You are permitted to use unconfirmed data sources (e.g. for politician headers) *only* if the frontend explicitly and visibly labels them as "unconfirmed".
3. **Classification Data First:** The directory should prefer normalized `politicians.government_level`, `government_branch`, `office_type`, and `jurisdiction` values. The keyword classifier in `DirectoryClient.tsx` is now only a compatibility fallback for rows that have not been migrated/backfilled; if you edit it, State & Federal rules must still sit above generic Local rules to avoid substring capturing errors.
4. **DCO Compliance:** Every single commit requires a Developer Certificate of Origin. You **must** append `--signoff` or `-s` to every `git commit` command (e.g., `git commit --signoff -m "message"`).
5. **Codex PR review feedback:** When asked to check or fix PR review feedback, start with GitHub CLI from PowerShell: `gh pr view <number> --json title,body,comments,reviews,latestReviews,files,url,mergeStateStatus,changedFiles` and `gh pr checks <number>`. Greptile's actionable issues are usually embedded in the PR body. Do not use browser automation, the Greptile connector, or UI inspection unless `gh` cannot access the public PR or the user explicitly asks for that route.
6. **Codex Windows Git workaround:** If normal sandboxed Git fails on `.git` lock files, use the documented Codex-owned worktree/clone flow such as `.codex-pr-<task>` for branch work instead of repeatedly retrying the locked main checkout. Git/GitHub CLI commands may still need the approved `git` or `gh` outside-sandbox command path for network/auth operations, but the repo workflow should stay centered on the Codex-owned worktree workaround.
7. **Local agent artifacts:** Do not leave Codex/agent scratch files visible as unstaged changes. Add purely local scratch patterns to `.git/info/exclude` when they should stay local, or add narrow project-safe patterns to `.gitignore` only when they should apply for everyone. Never include private key material such as `.codex-local-gnupg/` in a commit.
8. **Migrations are applied MANUALLY — there is no runner.** Nothing in CI applies
   `schema.sql` or `migrations/*.sql` to Supabase; `scraper.yml` only runs the ETL and
   `nextjs.yml` only builds. When you add a column/table/RPC in a migration, you (or the
   maintainer) must run it in the Supabase SQL editor, or the live DB silently drifts from
   the code. Drift is the #1 cause of "no data" outages here: the loader writes a column the
   live table lacks, **every** upsert fails with PGRST204, and (until this was fixed) the
   pipeline still reported success. All migrations are idempotent — safe to re-run in order.
   See README → "Applying migrations".
9. **Agent Configuration:** If you require additional capabilities to parse data, generate code, or analyze specific schemas, you must explicitly look up and add the appropriate agent skills or rules. We use non-frontier models for some tasks which need an extra push, so always configure the required skills before executing complex workflows.

## 🚀 Next Steps & Outstanding Work
- The groundwork is incredibly solid. The new agent should feel free to start building out any further visual analytics, user-authenticated features, or new scraper modules on top of this reliable foundation.
