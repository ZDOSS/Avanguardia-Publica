
Avanguardia Publica - Product & Technical Specification
1. Product Vision & Architecture Strategy
Avanguardia Publica is a public-facing political data transparency tool. The goal is to provide an unbiased, all-encompassing view of any politician using publicly available information.
The strategy enforces Radical Simplification. We are decoupling the data ingestion from the frontend entirely, focusing first on building simple, verifiable data pipelines that output to serverless databases without requiring complex container orchestration.
2. The Tech Stack (AI-Optimized)
Database & Backend API: Supabase (PostgreSQL). Provides a visual, spreadsheet-like interface for the database and automatically generates the APIs the frontend needs.
Data Ingestion (ETL Scraping): Python + GitHub Actions. GitHub Actions will run Python scraping scripts on a daily schedule, pushing data directly into Supabase.
Frontend Framework: Next.js (React) + Tailwind CSS. Configured for static export (output: 'export').
Hosting/Deployment: GitHub Pages for the frontend (zero-cost, static hosting) and GitHub Actions for the backend Python scripts.
IMPORTANT — static hosting, LIVE data: `output: 'export'` exports static page shells/routes for GitHub Pages; it does NOT bake the database into the build. Page data is read LIVE from Supabase in the browser at runtime via the supabase-js anon client (and Postgres RPC functions for computed views like Connections). Do not freeze query results into the static output — fetch live client-side, or add an RPC and call it with `supabase.rpc()`. See AGENTS.md → "Data flow" for the authoritative explanation.
3. Data Storage Logic & Schema Blueprint
To prevent data duplication and ensure accurate entity resolution, the database will strictly follow a "Hub-and-Spoke" model.
A. Strict Entity Resolution Rule
If third-party scrapers find a name that is not a 100% exact match to a verified politicians.full_name, the AI must not fuzzy-match it. The data must be routed to a pending_review table for manual approval by the admin.
B. Core Tables
The AI agents must build these exact tables in Supabase:
Table Name
Purpose
Key Columns & Upsert Logic
politicians
The Hub. One row per politician.
id (UUID), full_name, current_office, party, bioguide_id (Official US Gov ID), last_updated.
contact_info
Verified Spoke. Tied to politicians.id.
office_address, phone_number, official_website. Logic: Overwrite existing data on sync to ensure accuracy.
financial_disclosures
Verified Spoke (Money Out). Tied to politicians.id.
asset_name, asset_value_range, transaction_type (Buy/Sell), filing_date. Logic: Upsert (insert new, skip duplicates) based on filing_date.
campaign_donors
Verified Spoke (Money In). Tied to politicians.id.
donor_name, amount, donation_date, pac_status. Logic: Upsert based on unique transaction IDs from the FEC.
voting_records
Verified Spoke (The Record). Tied to politicians.id.
bill_name, bill_summary, vote_cast (Yea/Nay/Present), date.
unconfirmed_mentions
Third-Party Spoke. Tied to politicians.id.
source_api (WorldNews/LittleSis), content_summary, sentiment_score, url. Logic: Keep only the top 50 most recent entries per politician; delete older entries.

4. UI/UX Principles & Application User Flow
The frontend must be entirely read-only. The UI must feel like a modern, highly readable encyclopedia.
A. Core UI/UX Principles
Mobile-First Design: The layout must be perfectly usable on a smartphone. Data tables must be horizontally scrollable.
The "Visual Firewall": Official government data uses a clean, authoritative color palette. Third-party or unconfirmed data (from LittleSis or World News) must have a distinct visual shift (e.g., gray background) and a hardcoded "Third-Party Data - Unverified" badge.
B. View 1: The Landing Page (Minimalist)
Primary Element: A large, centered search bar supporting fuzzy-matching. As the user types, a dropdown instantly displays matching results.
Secondary Element: A simple "Browse Directory" button that opens a clean, alphabetical list of all politicians currently in the database. No trending feeds or algorithmic suggestions.
C. View 2: The Politician Hub (Profile Header)
Layout: Left-aligned official portrait. Right-aligned biographical data (Full Name, Party, Current Office).
Action Center: A clearly visible "Contact" section displaying official D.C./Local office addresses, phone numbers, and official websites.
D. View 3: The Data Spokes (Tabbed Navigation)
Directly beneath the Hub, dense data is categorized into horizontal, clickable tabs. Only one tab's data is rendered at a time.
Tabs: "Financial Disclosures" (Paginated table), "Campaign Donors" (Paginated table), "Voting Record" (List view), "Connections" (cross-referenced individuals — shared donors, co-voting allies/opponents, and network ties — rendered as a hub-and-spoke mini-graph over ranked, clickable relationship cards; fetched live via Postgres RPC), and "Media" (third-party news feed triggering the Visual Firewall). The verified connection types use the official palette; network ties sit behind the Visual Firewall. See docs/connections_design.md.
5. The Phased Rollout Plan
Development is strictly paced by data milestones to protect AI agents from generating conflicting code.
Phase 0.1: The Executive Branch Database Pipeline (Current Focus).
Objective: The agents write Python scripts to scrape data for the ~17 Executive Branch members (President, VP, Cabinet). They connect the scripts to Supabase. No web frontend.
Data Sources: Official Gov APIs, LittleSis, Wikidata, and World News API (Strictly limited to top 10 articles via pagination).
Verification: The Product Owner visually confirms the Supabase tables are populated correctly.
Phase 0.2: The Read-Only Frontend Foundation.
Objective: Build the Next.js application, implement the Minimalist Landing Page, the Hub profile layout, and the Visual Firewall. Deploy statically to GitHub Pages.
Phase 1: Scaling the Federal Hub.
Objective: Write pagination/rate-limiting logic to scrape the 100 US Senators and 435 House Representatives. Automate via GitHub Actions for nightly syncs.
Phase 2: State-Level Integration & Schema Chaos.
Objective: Build custom adapter scripts for two distinct states (e.g., California and New York) to prove the Supabase schema can handle non-federal CSV formats.
Phase 3: Local Data & Public Polish.
Objective: Integrate county/city records. Implement full-text search, final SEO optimization, and formal public launch.
Phase 4: International Expansion.
Objective: Adapt the engine for foreign jurisdictions and languages.

