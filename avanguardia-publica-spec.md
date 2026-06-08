# Avanguardia Publica — Project Spec

> Public-facing web application aggregating data on US politicians.  
> Repository: `https://github.com/ZDOSS/Avanguardia-Publica`

---

## 1. Overview

**Avanguardia Publica** is a public data transparency tool that automatically aggregates structured data about US federal and state politicians across four domains:

1. **Campaign donors** — contributions, PACs, committees
2. **Policy positions** — voting records derived from roll call votes, ideology scores
3. **Outside paid engagements** — lobbying records, financial disclosures
4. **Businesses & investments** — stock trades, financial holdings, government contracts

**Key principles:**
- **Fully automated** — no user submissions, no manual data entry (except admin-only tags)
- **Public-facing** — read-only, no login required
- **Data provenance** — every data point shows its source and last-synced date
- **Government vs. third-party disclaimers** — data from non-government sources carries a disclaimer
- **All politicians** — US federal (all), then state legislators incrementally as data sources are identified
- **All available history** — going back as far as each source provides records

---

## 2. Data Sources

### Confirmed Free/Public Sources

| # | Source | Covers | Format | Auth | Type |
|---|--------|--------|--------|------|------|
| 1 | **FEC API** (`api.open.fec.gov`) | Campaign contributions, committees, candidates, PACs, independent expenditures | REST JSON | API key (free at `api.data.gov`) | Government |
| 2 | **OpenSecrets Bulk Data** (`opensecrets.org/bulk-data`) | Contributions, lobbying, PACs, outside spending, personal finances, revolving door | CSV/text | Account + approval (free edu/nonprofit) | Third-party |
| 3 | **Congress.gov API** (`api.congress.gov`) | Bills, amendments, roll call votes, cosponsorships, member data | REST JSON | API key (free at `api.congress.gov/sign-up/`) | Government |
| 4 | **VoteView** (`voteview.com/data`) | DW-NOMINATE ideology scores, full roll call voting history (1789–present) | CSV/JSON + MongoDB dump (~500MB) | None | Third-party |
| 5 | **Senate LDA** (bulk + API) (`senate.gov` → `lda.senate.gov/api/`) | Lobbying registrations, quarterly reports, contributions (1999–2022 XML bulk; 2023+ REST API) | XML ZIPs + REST JSON | API key (free) | Government |
| 6 | **House Clerk Financial Disclosures** (`disclosures-clerk.house.gov`) | STOCK Act financial disclosures for House members | Web downloadable | None | Government |
| 7 | **USAspending.gov API** (`api.usaspending.gov`) | Federal contracts, grants, loans (trace to politically-connected entities) | REST JSON | None | Government |
| 8 | **SEC EDGAR API** (`sec.gov/search-filings/edgar-application-programming-interfaces`) | Corporate insider filings (Form 4) | REST JSON | None | Government |
| 9 | **Quiver Quant API** (`api.quiverquant.com`) | Congressional stock trades, net worth | REST JSON | Registration required | Third-party |
| 10 | **unitedstates/congress** (`github.com/unitedstates/congress`) | Bills, votes, committee data (community open-source scraper) | JSON/XML (self-host) | None | Third-party |

### Mapping Sources to Domains

| Domain | Sources |
|--------|---------|
| Campaign Donors | FEC API (#1), OpenSecrets (#2) |
| Policy Positions (via voting) | Congress.gov (#3), VoteView (#4), unitedstates/congress (#10) |
| Outside Paid Engagements | OpenSecrets (#2 — personal finances), Senate LDA (#5) |
| Businesses & Investments | House Clerk (#6), USAspending.gov (#7), SEC EDGAR (#8), Quiver Quant (#9) |
| Entity Resolution (ID crosswalks) | Congress.gov + VoteView + FEC |

---

## 3. Data Model (PostgreSQL)

```
Source  — tracks each data source, its refresh state
├── id, name, last_synced_at, sync_interval, status
├── config (jsonb), total_records, errors (text[])

Politician
├── id, name (first, middle, last, suffix, full_name)
├── party_history (jsonb[{party, start_date, end_date}])
├── state, district, chamber (house/senate/governor/state_house/state_senate)
├── bioguide_id (congress.gov), fec_ids[], lis_id, icpsr_id
├── voteview_id, govtrack_id, opensecrets_id
│   (cross-source identifiers for entity resolution)
├── photo_url, bio_text
├── in_office (bool), term_start, term_end[]
├── metadata (jsonb — extensible per-source fields)
├── created_at, updated_at, last_data_refresh

Organization  — PACs, committees, lobbying firms, businesses
├── id, name, type (pac/committee/lobbying_firm/corp/nonprofit)
├── fec_id, opensecrets_id
├── metadata (jsonb)

Contribution  — campaign donor / contribution
├── id, donor_name, donor_type (individual/pac/party/corp/union)
├── recipient_name (candidate or committee), committee_id
├── amount, date, election_cycle
├── fec_filing_id, amendment_indicator
├── employer, occupation, location (for individual donors)
├── source_name  (provenance: "fec_api", "opensecrets_bulk")
├── UNIQUE(fec_filing_id, donor_name, amount, date) — dedup

VotingRecord  — from congress.gov + VoteView
├── id, politician_id, roll_call_number, congress, session
├── bill_id, bill_title, bill_type, bill_number
├── vote (yea/nay/present/not_voting)
├── vote_date, issue_area
├── DW_NOMINATE_score (1D and 2D)
├── source_name

LobbyingRecord  — from Senate LDA
├── id, registrant_name, client_name, lobbyist_name
├── issue_area, issue_text, amount, report_quarter
├── filing_type (registration/quarterly/contribution)
├── government_entities_lobbied, source_xml_url
├── UNIQUE(lda_id)

PoliticianLobbyingRecord  — junction: politician ↔ lobbying (entity-resolved)
├── id, politician_id (FK → Politician), lobbying_record_id (FK → LobbyingRecord)
├── match_confidence (0.0–1.0), match_method (text[])
├── UNIQUE(politician_id, lobbying_record_id)

FinancialDisclosure  — stock trades + outside income
├── id, politician_id, filing_year, filing_type
├── asset_name, asset_type (stock/bond/real_estate/fund/crypto)
├── transaction_type (buy/sell/exchange)
├── amount_range_low, amount_range_high
├── notification_date, source_url, ticker
├── source_name (house_clerk/quiver/edgar)

GovernmentContract  — from USAspending.gov
├── id, award_id (USAspending unique), recipient_name
├── awarding_agency, amount, award_date, description
├── naics_code, place_of_performance
├── UNIQUE(award_id)

PoliticianGovernmentContract  — junction: politician ↔ contract (entity-resolved)
├── id, politician_id (FK → Politician), contract_id (FK → GovernmentContract)
├── match_confidence (0.0–1.0), match_method (text[])
├── UNIQUE(politician_id, contract_id)

Tag
├── id, name, slug, description
├── is_admin_only (t)
├── (polymorphic association to any entity)
```

### Design Notes
- `jsonb` for `external_ids`, `metadata`, `party_history` — allows per-country identifiers and extensible fields without schema changes
- `source_name` on every record for data provenance
- Composite UNIQUE constraints for idempotent upserts during syncs
- `PoliticianLobbyingRecord` and `PoliticianGovernmentContract` are junction tables populated by entity matching (e.g., matching `government_entities_lobbied` text or recipient names against politician names/committees). These are resolved asynchronously after raw data ingestion.
- PostgreSQL full-text search over politician names, donor names, organization names, bill titles

---

## 4. Architecture

### Hosting Split

| Component | Where | Why |
|-----------|-------|-----|
| **Frontend** | **GitHub Pages** | Free static hosting, custom domain compatible, CDN |
| **Backend API** | Railway / Fly.io | Managed Python hosting with background workers |
| **Database** | Railway / Supabase (PostgreSQL) | Managed PostgreSQL, colocated with backend |
| **Redis** | Railway addon / Upstash | Caching + Celery message broker |

### Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Frontend** | React 19 + TypeScript + Vite (SPA) | Static export, fast builds, great DX |
| **Styling** | Tailwind CSS + shadcn/ui | Rapid UI, accessible components, good for data-dense dashboards |
| **Routing** | React Router v7 | SPA routing |
| **Data Fetching** | TanStack Query v5 | Client-side caching, dedup, background refetch |
| **Charts** | Recharts | Lightweight, React-native, good for campaign finance/voting viz |
| **Backend API** | Python 3.12 + FastAPI | Data processing ecosystem (pandas, httpx), async HTTP, auto OpenAPI docs |
| **ETL Workers** | Celery + Redis | Battle-tested for periodic/incremental data sync |
| **ORM** | SQLAlchemy 2.0 + Alembic | Mature, complex query support, PostgreSQL features |
| **Caching** | Redis | API response caching, rate-limit tracking per source |
| **Auth** | None (public site); API keys for protected admin endpoints | Public read-only, admin-only write via API keys |

### Architecture Diagram

```
                   ┌─────────────┐
                   │  GitHub      │
                   │  Actions     │
                   │  (Scheduler) │
                   └──────┬───────┘
                          │ triggers Celery Beat or endpoint
                          ▼
┌─────────────────────────────────────────────────────────┐
│                    BACKEND (Railway)                     │
│                                                          │
│  Celery Beat ──► Workers ──► PostgreSQL                  │
│  (schedules)     (sync jobs)  (raw + normalized data)     │
│                                                          │
│  FastAPI ◄── Query ◄── PostgreSQL                        │
│    │                                                     │
│    └──► JSON REST API at api.avanguardapublica.com        │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼ HTTPS (CORS: GitHub Pages origin)
┌──────────────────────────────────────────────────────────┐
│                    GitHub Pages                           │
│  React SPA ──► TanStack Query ──► API                     │
│               (caches responses in memory)                │
└──────────────────────────────────────────────────────────┘
```

---

## 5. ETL Pipeline

### Sync Frequencies

| Source | Frequency | Notes |
|--------|-----------|-------|
| FEC API | Daily | Contributions trickle in; committees quarterly |
| OpenSecrets Bulk | On available dump | Periodic data dumps |
| Congress.gov API | Daily | New votes, bills as they happen |
| VoteView | Per congressional session | Bulk download after each session |
| Senate LDA (bulk ZIP) | Quarterly | XML dumps published quarterly |
| Senate LDA (API) | Daily | New lobbying filings |
| House Clerk Disclosures | Weekly | New STOCK Act filings |
| USAspending.gov | Weekly | Federal awards data |
| SEC EDGAR | Daily | New Form 4 filings |
| Quiver Quant | Daily (if free tier allows) | Congressional trade data |

### ETL Layers

1. **Ingestion Layer** — Source-specific adapters (HTTP client with rate limiting, bulk file downloader). Each adapter handles auth, pagination, incremental sync logic, and error/retry.

2. **Normalization Layer** — Maps source schemas → unified data model. Handles:
   - **Entity resolution**: Match politician across bioguide/fec/voteview/govtrack/opensecrets IDs. Congress.gov is authoritative for federal legislators. VoteView provides crosswalk between ICPSR/bioguide. Fuzzy name + state/district as fallback.
   - **Deduplication**: Composite unique keys prevent duplicate records on re-sync.
   - **Data quality**: Confidence scoring for entity resolution matches.

3. **Storage Layer** — Upsert into PostgreSQL. Raw source data optionally stored for audit/replay.

---

## 6. Core Features

### Politician Profile Page

- **Bio & Identifiers**: Full name, party history, state/district, chamber, photo, cross-source IDs
- **Campaign Finance Dashboard**:
  - Top donors by amount (sortable, filterable by cycle/industry)
  - Donations by industry/sector (bar/treemap chart)
  - Donation timeline across election cycles
  - PAC vs. individual donor breakdown
- **Voting Record**:
  - Recent votes with bill info and outcome
  - DW-NOMINATE ideology score (1D: Left-Right, 2D if available)
  - Issue area breakdown
  - Floor attendance rate
- **Lobbying & Influence**:
  - Lobbying firms that reported lobbying this politician's office
  - Industry sectors engaged
  - Outside income from financial disclosures
- **Financial Ties**:
  - Stock trades (STOCK Act disclosures)
  - Business investments and holdings
  - Connected federal contractors (entity matching with USAspending data)
- **Data Provenance Banner**: Every section shows source system + last-synced date. Third-party sources carry a disclaimer: _"Data sourced from OpenSecrets. Not independently verified."_

### Search & Discovery

- Full-text search across politicians, organizations, donors, bill titles
- Filter by state, party, chamber, committees
- Search by donor name, lobbying firm, company
- Paginated results with sort options

### Cross-Entity Views

- Organization profiles (PACs, lobbying firms, large corporate donors)
- "Follow the Money" flow: donor → PAC → politician → vote alignment
- Industry sector analysis (which sectors donate to whom, vote correlation)
- Election cycle summaries

### Admin Interface (API-key protected)

- Data source health dashboard (last sync, record counts, errors, rate limits)
- Trigger manual re-syncs per source
- Manage tags (the only manual data allowed)
- Resolve entity conflicts (when a politician can't be auto-matched across sources)

---

## 7. Project Structure

```
avanguardia-publica/
├── frontend/                       # React SPA (GitHub Pages)
│   ├── public/
│   ├── src/
│   │   ├── components/             # Reusable UI components
│   │   │   ├── ui/                 # shadcn/ui primitives
│   │   │   ├── PoliticianCard.tsx
│   │   │   ├── DonorChart.tsx
│   │   │   ├── VoteHistory.tsx
│   │   │   ├── FinancialDisclosures.tsx
│   │   │   ├── LobbyingTable.tsx
│   │   │   ├── DataSourceBadge.tsx  # Provenance + disclaimer
│   │   │   └── SearchBar.tsx
│   │   ├── pages/
│   │   │   ├── HomePage.tsx         # Search + featured
│   │   │   ├── PoliticianPage.tsx   # Full profile
│   │   │   ├── OrganizationPage.tsx
│   │   │   ├── SearchResultsPage.tsx
│   │   │   ├── ElectionCyclePage.tsx
│   │   │   └── AdminPage.tsx
│   │   ├── lib/
│   │   │   ├── api.ts              # API client (fetch wrapper)
│   │   │   ├── types.ts            # Shared TypeScript types
│   │   │   └── constants.ts        # Party colors, chamber names, etc.
│   │   ├── hooks/
│   │   │   └── use-query.ts        # TanStack Query wrappers
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── package.json
│   └── .github/workflows/deploy.yml  # Build + deploy to GitHub Pages
│
├── backend/                        # Python FastAPI
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routers/
│   │   │   │   ├── politicians.py
│   │   │   │   ├── contributions.py
│   │   │   │   ├── voting.py
│   │   │   │   ├── lobbying.py
│   │   │   │   ├── financials.py
│   │   │   │   ├── organizations.py
│   │   │   │   ├── contracts.py
│   │   │   │   ├── search.py
│   │   │   │   ├── tags.py
│   │   │   │   └── admin.py
│   │   │   └── deps.py            # Dependency injection (DB session, etc.)
│   │   ├── etl/
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # Abstract source adapter
│   │   │   ├── fec.py             # FEC API adapter
│   │   │   ├── congress_gov.py    # Congress.gov adapter
│   │   │   ├── voteview.py        # VoteView bulk importer
│   │   │   ├── opensecrets.py     # OpenSecrets bulk importer
│   │   │   ├── senate_lda.py      # Senate LDA adapter
│   │   │   ├── house_clerk.py     # House Clerk disclosures
│   │   │   ├── usaspending.py     # USAspending.gov adapter
│   │   │   ├── sec_edgar.py       # SEC EDGAR adapter
│   │   │   ├── quiver.py          # Quiver Quant adapter
│   │   │   ├── entity_resolver.py # Cross-source politician matching
│   │   │   └── tasks.py           # Celery task definitions
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── politician.py
│   │   │   ├── contribution.py
│   │   │   ├── voting.py
│   │   │   ├── lobbying.py
│   │   │   ├── financial.py
│   │   │   ├── contract.py
│   │   │   ├── organization.py
│   │   │   ├── source.py
│   │   │   └── tag.py
│   │   ├── schemas/               # Pydantic request/response schemas
│   │   │   ├── __init__.py
│   │   │   ├── politician.py
│   │   │   ├── contribution.py
│   │   │   └── ...etc
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py          # Settings (env vars)
│   │   │   ├── database.py        # SQLAlchemy engine + session
│   │   │   └── celery_app.py      # Celery instance
│   │   └── main.py                # FastAPI app entrypoint
│   ├── alembic/
│   │   ├── versions/
│   │   ├── env.py
│   │   └── alembic.ini
│   ├── tests/
│   ├── Dockerfile
│   ├── docker-compose.yml          # PostgreSQL + Redis for local dev
│   ├── pyproject.toml
│   └── Procfile                    # Railway: web + worker processes
│
├── README.md
└── LICENSE
```

---

## 8. Phased Roadmap

### Phase 1 — Foundation
- [ ] Project scaffolding (monorepo: `/frontend` + `/backend`)
- [ ] Docker Compose for local dev (PostgreSQL + Redis)
- [ ] Database schema, Alembic migrations
- [ ] ETL pipeline framework (abstract source adapter, Celery task registry)
- [ ] FEC API adapter (campaign contributions + candidates)
- [ ] Congress.gov adapter (members + bills)
- [ ] Entity resolution engine (bioguide ↔ fec ↔ icpsr crosswalk)
- [ ] Basic Politician API endpoints (list, detail)
- [ ] Basic SPA shell (Vite + Tailwind + React Router)

### Phase 2 — Richer Data
- [ ] VoteView bulk importer (voting records + ideology scores)
- [ ] Voting/policy API endpoints
- [ ] OpenSecrets bulk data importer (enrichment of contribution data)
- [ ] Campaign finance API endpoints (contributions, committees, PACs)
- [ ] Full politician profile pages in frontend
- [ ] Campaign finance dashboard (DonorChart, contribution breakdown)

### Phase 3 — Financial & Influence
- [ ] Senate LDA adapter (lobbying records)
- [ ] House Clerk disclosures adapter (stock trades)
- [ ] USAspending.gov adapter (government contracts)
- [ ] SEC EDGAR adapter (corporate insider filings)
- [ ] Quiver Quant adapter (congressional trades)
- [ ] Lobbying, financial disclosure, and contract API endpoints
- [ ] Organization profiles and cross-entity views
- [ ] "Follow the Money" flow visualizations
- [ ] Data provenance badges & third-party disclaimers on all views

### Phase 4 — Polish & Search
- [ ] PostgreSQL full-text search (tsvector across politicians, orgs, donors, bills)
- [ ] Search API endpoint + frontend search UX
- [ ] Data source health dashboard (admin)
- [ ] Tag management (admin)
- [ ] Performance optimization (materialized views, Redis caching)
- [ ] Mobile-responsive design pass
- [ ] GitHub Actions: deploy frontend to GitHub Pages

### Phase 5 — State-Level & International
- [ ] Identify state-level data sources per state
- [ ] Country/region abstraction layer in data model (`country_code`, `region`)
- [ ] Per-state source adapters (starting with states that have APIs)
- [ ] Canada Elections CSV importer (as first international source)
- [ ] Multi-country politician profiles

---

## 9. API Design (Key Endpoints)

```
GET  /api/politicians                  # List with pagination, filters, search
GET  /api/politicians/{id}             # Full profile (includes aggregated stats)
GET  /api/politicians/{id}/contributions    # Campaign contributions
GET  /api/politicians/{id}/voting           # Voting records
GET  /api/politicians/{id}/lobbying         # Lobbying records
GET  /api/politicians/{id}/financials       # Stock trades + disclosures
GET  /api/politicians/{id}/contracts        # Linked government contracts

GET  /api/organizations                # PACs, firms, companies
GET  /api/organizations/{id}

GET  /api/contributions               # All contributions with filters
GET  /api/voting-records              # All votes with filters
GET  /api/lobbying-records
GET  /api/financial-disclosures
GET  /api/government-contracts

GET  /api/search?q=...&type=...       # Full-text search

# Admin (API-key protected)
GET  /api/admin/sources               # Data source health
POST /api/admin/sources/{id}/sync     # Trigger manual sync
GET  /api/admin/entity-conflicts      # Unresolved entity matches
POST /api/admin/entity-conflicts/{id}/resolve
GET  /api/admin/tags                  # CRUD tags
POST /api/admin/tags
```

All public endpoints are read-only. Admin endpoints require `X-API-Key` header.

---

## 10. Key Technical Decisions

### Entity Resolution
Congress.gov is the authoritative source for federal legislators. The seed flow is:
1. Fetch all current federal members from Congress.gov `/member/` endpoint
2. VoteView provides crosswalk files mapping bioguide ↔ icpsr ↔ other IDs
3. FEC candidates matched via FEC ↔ bioguide mapping available from FEC API
4. OpenSecrets CIDs mapped via name + state/district as fallback
5. Unmatched entities land in admin resolution queue

### Data Provenance
Every record carries `source_name` (e.g. `"fec_api"`, `"opensecrets_bulk"`, `"congress_gov_api"`). The UI renders a `DataSourceBadge` component:
- Government sources: green badge with source name
- Third-party sources: amber badge with source name + disclaimer tooltip

### Rate Limiting
Each ETL adapter includes rate-limit awareness (respects `Retry-After` headers, tracks remaining calls) and staggered scheduling to avoid concurrent rate limit exhaustion.

### Idempotency
All sync operations are upserts using composite UNIQUE constraints. Running the same sync job twice produces the same database state — no duplicates.

---

## 11. Environment Variables

```env
# Backend (.env)
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
API_KEY_DATA_GOV=...          # FEC + Congress.gov API key (free)
SENATE_LDA_API_KEY=...        # Senate LDA API key
OPENSECRETS_BULK_PATH=...     # Local path to downloaded bulk data
QUIVER_QUANT_API_KEY=...      # Quiver Quant API key
ADMIN_API_KEY=...             # For protected admin endpoints
CORS_ORIGINS=https://zdoss.github.io,http://localhost:5173

# Frontend (.env)
VITE_API_URL=https://api.avanguardapublica.com
```

---

## 12. Notes for Implementation

1. **Frontend is purely static** — no SSR, no server functions. All data comes from the REST API. TanStack Query handles loading/error/caching states.

2. **Backend is the heavy lifter** — all data ingestion, normalization, entity resolution, and serving. Celery workers run on a separate process (Procfile: `worker` process).

3. **Start with FEC + Congress.gov** — these are the two most data-rich, free, and reliable sources. Everything else is enrichment.

4. **OpenSecrets bulk data** — requires an account and approval via `opensecrets.org/bulk-data/signup`. This is handled by the project owner.

5. **No authentication for public users** — the site is entirely read-only for visitors. Admin endpoints use API-key auth.

6. **GitHub Pages deployment** — the frontend is built with `vite build` and deployed via GitHub Actions. The `.github/workflows/deploy.yml` file handles build + push to `gh-pages` branch.

7. **CORS must be configured** on the backend to allow the GitHub Pages origin.

8. **State-level data is a Phase 5 concern** — the architecture supports it but don't build it until federal is solid.
