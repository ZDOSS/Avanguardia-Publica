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

**The consequence:** after a scraper run writes new data, search and directory can link to
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
5. **Codex PR review feedback:** When asked to check or fix PR review feedback, start with
   GitHub CLI from the repository shell:
   `gh pr view <number> --json title,body,comments,reviews,latestReviews,files,url,mergeStateStatus,changedFiles`
   and `gh pr checks <number>`. Greptile's actionable issues are usually embedded in the PR
   body. Do not use browser automation, the Greptile connector, or UI inspection unless `gh`
   cannot access the public PR or the user explicitly asks for that route.
6. **Git branch and lock safety:** For new work, fetch the base and create the task branch
   directly from `origin/main` without synchronizing local `main` unless the active goal
   authorizes that synchronization. If Git reports a lock, identify any live Git process
   before doing anything else; do not repeatedly retry and do not delete a lock merely because
   it exists. Use a task-specific Codex-owned worktree only when the normal checkout is
   genuinely unavailable.
7. **Local agent artifacts:** Do not leave Codex/agent scratch files visible as unstaged changes. Add purely local scratch patterns to `.git/info/exclude` when they should stay local, or add narrow project-safe patterns to `.gitignore` only when they should apply for everyone. Never include private key material such as `.codex-local-gnupg/` in a commit.
8. **Migrations are applied MANUALLY — there is no runner.** Nothing in CI applies
   `schema.sql` or `migrations/*.sql` to Supabase; `scraper.yml` only runs the ETL and
   `nextjs.yml` only builds. When you add a column/table/RPC in a migration, you (or the
   maintainer) must run it in the Supabase SQL editor, or the live DB silently drifts from
   the code. Drift is the #1 cause of "no data" outages here: the loader writes a column the
   live table lacks, **every** upsert fails with PGRST204, and (until this was fixed) the
   pipeline still reported success. Historical migrations are **forward-only**: apply each
   one once in filename order. Starting with `0022`, each migration records itself in
   `public.schema_migrations`. Never replay the full directory on an upgraded database; data
   migrations such as `0011`, `0015`, and `0016` preserve decisions whose meaning changes
   after later migrations. Add a new repair migration instead. See README → "Applying
   migrations".
9. **Agent Configuration:** If you require additional capabilities to parse data, generate code, or analyze specific schemas, you must explicitly look up and add the appropriate agent skills or rules. We use non-frontier models for some tasks which need an extra push, so always configure the required skills before executing complex workflows.
10. **Goal-scoped PR authority and `main` synchronization:** This is a limited permission the
    user may explicitly grant for an active user-set goal; it is never a general agent
    permission.
    - Before starting new work, check for open PRs. Keep exactly one PR open for that goal and
      finish it before opening another.
    - When the user has delegated autonomous PR review/merging for the active goal, inspect
      Greptile and checks no more often than every five minutes while a review is pending. Do
      not busy-loop or block on a long sleep.
    - Before deciding whether a PR is ready, read the **entire** current PR body and every part
      of the Greptile review block. A confidence score, summary, check label, or inline
      comments alone never proves that there are no actionable findings.
    - Merge only after the full current PR body shows a Greptile **5/5** review whose **Last
      reviewed commit** matches `headRefOid`, no actionable findings remain, required checks
      (including DCO) pass, and GitHub reports no merge conflict.
    - A merge is not complete merely because the merge command returned. Confirm that GitHub
      reports `MERGED`, obtain the merge commit, fetch `origin`, confirm that commit is in
      `origin/main`, then fast-forward local `main` with `git pull --ff-only origin main` and
      verify the worktree is clean.
    - Outside an active user-set goal with this explicit delegation, do **not** merge PRs or
      check out, pull, fast-forward, or otherwise synchronize local `main` from `origin`; the
      user retains those responsibilities.
11. **Outcome-sized delivery, commits, and validation:** Progress is measured by complete,
    demonstrable capabilities and roadmap acceptance criteria, not by the number of files,
    commits, pull requests, migrations, or review checkpoints produced.
    - Before implementation, state the user- or operator-visible outcome and its acceptance
      criteria. The default delivery unit is one reviewable PR for that end-to-end outcome,
      including the schema/migration, backend or scraper behavior, frontend, tests, and concise
      documentation needed to make it usable when those pieces share a rollback boundary.
    - A file, technical layer, migration, provenance field, shadow mode, feature flag, workflow
      toggle, schedule change, review marker, or documentation update is not automatically a
      useful slice. Do not split these into consecutive PRs when they merely prepare the next
      change. Use internal gates or disabled-by-default paths inside one cohesive PR when that
      keeps rollout safe.
    - Size each delivery in proportion to risk: **smaller if risky, bigger if safer.** Use a
      smaller independently provable slice when uncertainty, irreversible migration or data-loss
      potential, a security boundary, external evidence, or rollback blast radius prevents the
      whole outcome from being validated safely together. Use a larger cohesive slice when the
      work is low-risk or read-only, relies on proven contracts, shares one rollback and
      validation boundary, and splitting it would leave preparatory plumbing instead of usable
      progress. File counts, line counts, and an arbitrary preference for small PRs are never
      sufficient reasons to split work.
    - A smaller split must still end at an independently usable outcome or a genuinely distinct
      boundary, such as evidence that must be gathered from a real external service before the
      next stage can be designed safely, an urgent production repair, or an external dependency
      that prevents completion. State the concrete reason for the split and the deferred
      dependency in the PR body. Keep unrelated refactors out; a safer larger slice must remain
      cohesive and reviewable rather than becoming unbounded.
    - Aim for one to three meaningful commits per PR. Organize commits around coherent review
      units rather than individual files or tiny edits. Prepare and validate the complete slice
      before the first push when practical; add follow-up commits for substantive review or CI
      findings, not cosmetic churn. Avoid standalone documentation, planning, agent-rule, or
      enablement PRs unless the maintainer explicitly requests one or the change is independently
      valuable.
    - During implementation, run the smallest targeted tests that provide useful feedback. Run
      the full relevant validation once before pushing the completed slice, and repeat expensive
      validation only after a change that could affect its result. Do not rerun unchanged suites
      merely to create activity.
    - Run the full scraper manually only when its end-to-end data behavior is part of the
      acceptance criteria. Prefer fixtures, preflight checks, and focused tests for documentation,
      UI-only, or workflow-metadata changes. Do not run it merely because a PR opened or merged;
      continue to obey the no-overlap, hourly-spacing, and daily-limit rules below.
    - Treat normal release proof—manual migration application, a justified canary, database
      reconciliation, and browser validation—as completion of the same milestone, not as a reason
      to create another PR. Open a repair PR only when that proof identifies an actual code or
      configuration change.
    - Progress reports must lead with capabilities that are usable or demonstrable, acceptance
      criteria completed, remaining outcomes, and material risks. Commit counts, PR counts, file
      counts, and lines changed are supporting context only.

## 🚀 Next Steps & Outstanding Work
- The active remaining roadmap is `docs/canonical_data_and_analytics_plan.md`. Phases 1 and
  2 are implemented and the scraper identity resolver in Phase 3 is complete. Applied migrations
  `0022` through `0038` establish deterministic identity, atomic source-profile writes,
  provenance, person office terms, and private normalized House and Senate roll-call facts.
  Both official vote paths remain bounded, identifier-only, and
  isolated from legacy `voting_records`; the versioned `0031` read RPC combines presentation-safe
  official facts with legacy state/historical coverage without opening the private tables, and
  `0032` repairs that RPC's query plan while preserving its result contract. `0033` keeps
  ambiguous same-day GovTrack signature collisions visible unless exactly one official roll call
  matches. `0034` records the candidate Congress.gov detail-only metadata shadow contract.
  `0035` approves only the observed bounded detail path and adds private source-record-backed
  measure facts, exact official-roll-call links, and one atomic service-role writer without raw
  JSON, legacy vote writes, or a public read path. `0036` records the successful manual canary
  and private audit before the reviewed workflow enabled that same bounded path for schedules.
  `0037` adds a narrow measure-aware public voting-record RPC without opening those private
  tables or changing the v2 vote contract. `0038` adds bounded official participation summaries,
  canonical same-scope alignment rankings, and inspectable pairwise evidence while keeping
  state/historical legacy votes separate; both migrations are applied and live-validated.
- Monitor and resolve quarantined identity candidates instead of weakening the pre-write
  boundary. A person can have federal, state, and local roles over time; those roles must
  not become separate canonical people or be flattened into one office field.
- The first ten scheduled Senate write workflows completed successfully through August 10,
  2026, and the first five detailed run audits had complete reconciliation, healthy writes,
  exact provenance/identity coverage, and zero legacy vote keys. After migrations `0031` through
  `0033` are applied and the live Voting Record tab is validated on representative House and Senate
  profiles, the bounded Congress.gov bill/amendment metadata path is now implemented. It consumes
  only exact identifiers from the existing official-vote windows, makes at most 100 detail calls,
  and initially wrote no database facts. Migration `0034` is applied, the
  `CONGRESS_GOV_API_KEY` secret is provisioned, and three production-key observations each
  completed all 18 bounded detail calls with healthy source status, covering 15 bills, three
  amendments, and 43 exact links. The operational hardening slice now separates real
  news-provider attempts, suppressed demand, local caps, upstream quota headers, and breaker
  causes, and repairs GDELT's TLS-safe public-storage path. Migration `0035` is applied, and
  manual canary `31833856216` completed all 18 detail calls and one healthy atomic write of 18
  private measures (15 bills and three amendments) plus 43 exact links across 40 roll calls.
  The database audit and exact replay found zero provenance, fact, link, ACL, legacy-key, row-image,
  or transaction-ID violations. Migration `0036` is applied, and three scheduled enabled runs
  each completed the exact 18-detail / 18-measure / 43-link / 40-roll-call contract with healthy
  writes; the post-observation live audit found zero violations. The first post-PR-109 scheduled
  run confirmed that the legacy person-filtered GovTrack crawl had zero attempts or failures while
  the official House, Senate, and Congress.gov paths stayed healthy. Migration `0037` is now
  applied: v3/v2 base-row equivalence, all 43 exact measure links across 40 roll calls, browser
  ACLs, pagination, and representative House/Senate profiles were validated live. Migration
  `0038` is also applied: anonymous-role House/Senate summary, alignment, and pair-evidence
  reconciliations passed with zero ACL or contract violations, and scraper preflight now requires
  the complete analytics surface. The scraper
  cron is intentionally paused during active development. Use only the manual workflow, keep the
  state LittleSis fields blank and GovTrack profile mode disabled for routine runs, explicitly
  enable the reviewed House/Senate/Congress.gov modes when refreshing those facts, and never
  overlap runs. Allow at least one hour between full runs and ordinarily no more than three per
  UTC day while OpenStates is active; do not restore the schedule without a reviewed change and
  maintainer decision. Future historical GovTrack refresh should use a separately bounded,
  checkpointed backfill.
