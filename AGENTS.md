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

### 🔑 Data flow: Supabase is read LIVE in the browser — data is NOT baked into the build
This is the single most-misread part of the architecture, so read it before touching any
page or data-fetching code:

- `output: "export"` (in `next.config.ts`) makes the build emit **static page shells +
  routes** for GitHub Pages hosting. **It does NOT mean the data is frozen at build time.**
  The export is *hosting*, not a data snapshot.
- The **data is fetched live from Supabase in the user's browser at runtime**, via the
  `@supabase/supabase-js` anon client (`frontend/src/lib/supabase.ts`) — exactly like the
  directory (`fetchAllPoliticians` in `lib/politicians.ts`, called from `page.tsx`) and the
  profile **Connections** tab (`supabase.rpc(...)` in `lib/connections.ts`). New data views
  should follow this same client-side pattern, or call a Postgres RPC, so the page always
  reflects the current database without a rebuild.
- **Do not** "solve" data display by baking query results into the static output or by
  precomputing tables just to avoid a live query. If you need server-side aggregation,
  add a Supabase **RPC function** (`SECURITY DEFINER`, `GRANT EXECUTE ... TO anon`) and call
  it live with `supabase.rpc()` — see `migrations/0003_connections.sql` for the pattern.
- The one build-time exception today: `[politician_id]/page.tsx` pre-renders the static
  route list (`generateStaticParams`) and the profile **hub header** fields. Everything
  dynamic on the profile (connections, and anything you add) is fetched live client-side.
  Treat live client-side reads as the default; build-time fetching is only for enumerating
  routes, not for freezing displayed data.

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
3. **Classification Order:** When modifying the keyword classifiers in `DirectoryClient.tsx`, remember that Javascript evaluates array rules sequentially. State & Federal rules must always sit above generic Local rules to avoid substring capturing errors.
4. **DCO Compliance:** Every single commit requires a Developer Certificate of Origin. You **must** append `--signoff` or `-s` to every `git commit` command (e.g., `git commit --signoff -m "message"`).
5. **Agent Configuration:** If you require additional capabilities to parse data, generate code, or analyze specific schemas, you must explicitly look up and add the appropriate agent skills or rules. We use non-frontier models for some tasks which need an extra push, so always configure the required skills before executing complex workflows.

## 🚀 Next Steps & Outstanding Work
- The groundwork is incredibly solid. The new agent should feel free to start building out any further visual analytics, user-authenticated features, or new scraper modules on top of this reliable foundation.
