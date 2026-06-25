# Data-Driven App and Analytics Plan

This plan captures the next major direction for Avanguardia Publica: make the app fully
data-driven from Supabase first, then harden the pipeline and documentation around that
model, then add visual analytics on top of reliable live data.

## Goal

Move the product toward a consistent model:

- GitHub Pages serves a static application shell.
- Supabase remains the live source of truth.
- User-visible profile data is fetched at runtime from the browser or via Postgres RPC.
- Build-time work is limited to shipping the app and, where unavoidable, pre-rendering
  optional SEO routes.

The practical test: when the scraper writes new data to Supabase, the app should show it
without needing a frontend rebuild, except for explicitly documented static SEO pages.

## Phase 1: Make Profile Data Fully Data-Driven

The current app is hybrid. Home/search, directory, and the profile Connections tab are live
browser reads. Most profile content is still baked into static profile pages during
`npm run build`. This phase removes that mismatch.

### Phase 1 Progress

Implemented in the live-profile-spokes chunk:

- `/profile?id=<uuid>` is the reliable live profile route used by search/directory links.
- Profile header and official contact have focused live helpers in `frontend/src/lib/profile.ts`.
- Financial disclosures, campaign donors, voting records, and media mentions have dedicated
  ranged helpers in `frontend/src/lib/`.
- Official Contact, Financial Disclosures, Campaign Donors, Voting Record, and Media now render
  as client-fetched views with loading, error, empty, retry, pagination, and freshness cues.
- The legacy `/[politician_id]` page no longer bakes profile spokes; it only generates the static
  route shell/header for SEO compatibility.

Remaining follow-up: decide whether legacy pretty profile headers should also re-fetch their hub
fields client-side, or whether `/profile?id=<uuid>` should remain the canonical live route while
pretty pages are SEO snapshots.

### 1.1 Add Live Profile Data Helpers

Create focused frontend data helpers in `frontend/src/lib/` for profile spokes:

- `profile.ts`: hub/header fields and contact info.
- `financialDisclosures.ts`: financial disclosure filings.
- `campaignDonors.ts`: donor rows with pagination support.
- `votingRecords.ts`: roll-call votes with pagination and filters.
- `mediaMentions.ts`: unconfirmed mentions, clearly flagged as third-party data.

These helpers should use the existing Supabase anon client and should page with `.range()`
where result sets can exceed 1,000 rows.

### 1.2 Convert Profile Tabs to Client-Fetched Views

Move the following out of build-time page payloads and into client components:

- Official Contact
- Financial Disclosures
- Campaign Donors
- Voting Record
- Media

Keep the existing Connections pattern as the model:

- client component owns loading, error, empty, and success states
- verified data uses the official visual palette
- unverified data remains behind the Visual Firewall
- each lane can fail independently where possible

### 1.3 Decide How to Handle Dynamic Profile Routes (user prefers option 1)

Because `output: "export"` has no runtime server, `/[politician_id]` routes are still
generated at build time. To avoid new database rows appearing in search but linking to a
404, choose one of these patterns:

1. Add a live `/profile?id=<uuid>` route.
   - Directory/search can link there immediately for every Supabase row.
   - Existing static `/[politician_id]` pages can remain for SEO.
   - This is the simplest way to make navigation fully data-driven on GitHub Pages.

2. Keep `/[politician_id]` as the only profile route.
   - Continue relying on the scraper workflow triggering a Pages deploy.
   - Document that route availability refreshes on deploy, not instantly.

Recommended and selected: add `/profile?id=<uuid>` as the reliable live route, then decide
later whether pretty static profile routes are still worth maintaining for SEO.

### 1.4 Add Runtime Freshness Indicators

Expose `last_updated` or source-specific timestamps in the UI:

- profile header: last updated
- contact info: last updated
- table tabs: latest row date or empty-state explanation
- media: ingestion/source timestamp if available

This makes the live-data model visible and helps debug stale records.

## Phase 2: Data and Pipeline Hardening

Once the UI is consistently live, tighten the pipeline so it is easier to trust.

### Phase 2 Progress

Implemented in the schema-preflight chunk:

- The scraper runs a startup schema preflight against the live Supabase PostgREST surface
  before extractor work begins.
- The preflight verifies the migrated hub/spoke columns needed by the current loader and
  the Connections RPC functions used by the live frontend.
- Drift now fails fast with a migration-oriented fatal message instead of spending API
  quota and reporting a late partial run.

### 2.1 Add Schema Preflight

Before the scraper starts a long run, check that Supabase has the required columns,
indexes, tables, and RPC functions for the current code.

Minimum checks:

- `politicians.state`
- `politicians.district`
- `politicians.external_ids`
- `voting_records.roll_call_id`
- `voting_records.jurisdiction`
- `relationships`
- `financial_disclosures.doc_id`
- `financial_disclosures.doc_url`
- `financial_disclosures.filing_type`
- `get_shared_donors(uuid)`
- `get_covoting(uuid)`
- `get_network_ties(uuid)`

Fail fast with a clear migration message when anything is missing.

### 2.2 Add ETL Run Summary

At the end of each scraper run, print and optionally upload a structured summary:

- hub rows inserted/updated
- contact rows updated
- donor rows written
- voting rows written
- relationship rows written
- media mentions inserted
- financial disclosure filings written
- source-specific skips
- source-specific breaker trips
- schema preflight status

This will make GitHub Actions logs much easier to read.

### 2.3 Normalize Classification Data

The directory currently classifies offices in the frontend from `current_office` strings.
That works, but it will get brittle as coverage expands.

Add normalized columns or a derived table for:

- government level: federal, state, local
- branch: executive, legislative, judicial
- office type: senator, representative, governor, mayor, justice, etc.
- jurisdiction: US, state code, county, city, district

The frontend can still render the current taxonomy, but it should not need to infer all
structure from display text.

### 2.4 Add Source Metadata

For each spoke, track enough provenance to explain the data:

- source name
- source URL or source record ID
- ingestion method
- last fetched timestamp
- verified vs unverified lane

This supports trust labels, debugging, and future source comparison.

## Phase 3: Product Improvements After Data-Driven Conversion

These improvements become safer once all profile data is runtime-fetched.

### 3.1 Better Profile UX

- Add per-tab loading skeletons and retry buttons.
- Add pagination for donors, votes, media, and disclosures.
- Add sorting/filtering inside high-volume tabs.
- Add deep links for tabs, for example `/profile?id=<uuid>&tab=votes`.
- Add clear empty states that explain whether data is unavailable, not yet ingested, or not
  applicable to that office.

### 3.2 Search Improvements

- Move large search workloads to Supabase full-text search or RPC.
- Support office, state, party, and jurisdiction filters from normalized columns.
- Add typo-tolerant search only for UI discovery, never for verified identity joins.

### 3.3 Admin/Data Quality Backlog

Eventually add a private workflow or table for:

- pending identity review
- suspected duplicates
- source mismatches
- unresolved relationship names
- failed enrichment attempts

This preserves the strict identity rule while making cleanup manageable.

## Phase 4: Additional Connections We Can Derive From Existing Data

The app already has three connection lanes:

- shared donors from `campaign_donors`
- co-voting from `voting_records`
- direct network ties from `relationships`

There are several more useful relationship views we can derive from the data already being
stored, without adding paid sources.

### 4.1 Donor Network Enhancements

Useful derived views:

- Top shared donors between two politicians.
- Donor overlap score normalized by each politician's donor count.
- PAC-only overlap vs individual-only overlap.
- Largest shared donor entities by total amount.
- Donor bridge view: one donor or PAC connected to every politician it funded.

This shows financial overlap without implying wrongdoing. The UI should phrase it as
"shared donor records" or "recorded donor overlap," not influence.

### 4.2 Voting Similarity and Opposition

Current co-voting can expand into:

- agreement over time
- agreement by jurisdiction
- most divisive shared votes
- strongest consistent opponents
- clusters of legislators who frequently vote together

This turns raw voting records into a readable political map while staying grounded in exact
roll-call IDs.

### 4.3 Two-Hop Relationship Overlap

The `relationships` table can show more than direct LittleSis ties:

- Politicians connected to the same outside organization.
- Politicians connected to the same person.
- Organization-centered pages: one organization linked to many politicians.
- Relationship-type filters when available from the source.

This must remain behind the Visual Firewall unless independently verified, because these
are third-party network ties.

### 4.4 Geographic and Office Cohorts

From `politicians.state`, `district`, and `current_office`, we can show:

- same-state delegation connections
- same chamber connections
- same office-type cohorts, such as governors or state attorneys general
- state-level dashboards showing all tracked officials in one jurisdiction

### 4.5 Media Co-Mention Patterns

From `unconfirmed_mentions`, we can cautiously derive:

- politicians mentioned by the same source URL
- politicians with repeated coverage from the same source API
- co-mentioned names when article metadata supports it
- media volume over time by politician

These are discovery signals only. They must stay unverified and should not be mixed with
official-record connections.

### 4.6 Disclosure Filing Patterns

With House Clerk filing-level disclosures, we can show:

- filing timeline per House member
- recent filing activity across the House
- members with many periodic transaction reports
- filing-type breakdowns

The current official feed stores filing-level records, not parsed transaction-level asset
rows. The UI should link to PDFs and avoid claiming asset-level analysis until PDF parsing
is implemented and verified.

## Phase 5: Visual Analytics

Only start this phase after the live data model and basic hardening are in place.

Candidate views:

- Profile-level connection map
- State dashboard
- Donor/PAC explorer
- Voting cluster view
- Data freshness dashboard

Visualization rules:

- Verified data and unverified data must never share the same visual treatment.
- Every chart should expose the underlying records or link to the relevant tab.
- Avoid implying causation from correlation.
- Prefer simple, inspectable visuals over decorative dashboards.
- Keep mobile layouts readable before adding complex graph interactions.

## Recommended Build Order

1. Add `/profile?id=<uuid>` live profile route.
2. Move Contact, Financial, Donors, Voting, and Media into live client tabs.
3. Add pagination, loading, error, empty, and freshness states.
4. Add schema preflight to the scraper.
5. Add ETL summary reporting.
6. Normalize government classification fields.
7. Add richer connection RPCs.
8. Build visual analytics on top of those RPCs.
