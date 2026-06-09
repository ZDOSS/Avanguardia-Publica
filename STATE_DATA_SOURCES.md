# State-Level & International Data Sources

This is a working catalog of state and international public sources that
can be plugged into the Avanguardia Publica ETL. The architecture is
agnostic about country/jurisdiction, but only sources marked with a
✅ in the **Adapter shipped** column have an actual Python adapter
checked into `backend/app/etl/`.

The catalog is intentionally conservative: we ship adapters only after
confirming the data is

1. Free / public (no paywall, no per-request license)
2. Available as a structured bulk download or a documented open API
3. Stable enough that we can write a schema mapping that won't churn
   every release

A ❌ means we *want* to ship the adapter but haven't yet — either
because the source is unstable, the schema is non-trivial, or the
project hasn't allocated time to it.

---

## US state legislatures (campaign finance & legislator catalogs)

| State | Source | Format | Auth | Adapter shipped |
|-------|--------|--------|------|-----------------|
| California | [Cal-Access](https://cal-access.sos.ca.gov/downloads/) | CSV bulk export | None | ✅ `ca_calaccess` |
| New York | [NYS BOE](https://www.elections.ny.gov/CFViewReports.html) | CSV / PDF | None | ❌ (planned) |
| Texas | [Texas Ethics Commission](https://www.ethics.state.tx.us/search/cf/) | CSV bulk | None | ❌ (planned) |
| Florida | [FL Division of Elections](https://dos.myflorida.com/elections/data-statistics/) | CSV | None | ❌ |
| Illinois | [IL State Board of Elections](https://www.elections.il.gov/campaigndisclosure.html) | CSV | None | ❌ |
| Massachusetts | [MA OCPF](https://www.ocpf.us/Reports) | CSV | None | ❌ |
| Washington | [WA PDC](https://www.pdc.wa.gov/browse/macro-reports) | CSV | None | ❌ |
| Oregon | [OR ORESTAR](https://egov.sos.state.or.us/orsestar/) | CSV | None | ❌ |
| Colorado | [CO TRACER](https://tracer.sos.colorado.gov/PublicSite/SearchPage.aspx) | CSV | None | ❌ |
| Maryland | [MD State Board of Elections](https://elections.maryland.gov/campaign_finance/index.html) | CSV | None | ❌ |
| Virginia | [VA Department of Elections](https://www.elections.virginia.gov/castar/) | CSV | None | ❌ |
| Pennsylvania | [PA Dept. of State](https://www.dos.pa.gov/VotingElections/CandidatesCommittees/CampaignFinance/) | CSV | None | ❌ |

**Selection criteria for the first state:** California was chosen
because (a) the largest state legislature in the US, (b) Cal-Access is
the only state-level source that publishes the same year-over-year
schema (vs. states that change column names with every release), and
(c) the data is downloaded as a single zipped CSV bundle, matching our
existing OpenSecrets bulk-importer pattern.

**Per-state adapter pattern:** each state adapter follows the same
shape as `ca_calaccess.py` — read a bulk CSV from a local path
specified by an env var, normalize to the unified `Politician` model
with `country_code='US'`, `jurisdiction_level='state'`, and a chamber
value of `state_house` / `state_senate` / `governor` (already supported
by the existing `chamber` column).

## International

| Country | Source | Format | Auth | Adapter shipped |
|---------|--------|--------|------|-----------------|
| Canada (federal) | [Elections Canada open data](https://open.canada.ca/) | CSV bulk | None | ✅ `canada_elections` |
| Canada (campaign finance) | [Elections Canada returns](https://www.elections.ca/fin/lim/default.aspx?lang=e) | CSV bulk | None | ❌ (planned) |
| UK (parliament) | [UK Parliament Members API](https://members-api.parliament.uk/) | REST JSON | None | ❌ |
| UK (spending) | [Electoral Commission](https://www.electoralcommission.org.uk/regulatory-areas/party-finance-and-spending) | CSV bulk | None | ❌ |
| Australia (federal) | [AEC Tenders and Donations](https://www.aec.gov.au/parties_and_representatives/financial_disclosure/) | CSV / XLSX | None | ❌ |
| New Zealand | [NZ Electoral Commission](https://elections.nz/finance/returns/) | CSV | None | ❌ |
| Germany (Bundestag) | [Bundestag open data](https://www.bundestag.de/services/opendata) | XML / CSV | None | ❌ |
| France (National Assembly) | [data.assemblee-nationale.fr](https://data.assemblee-nationale.fr/) | JSON / XML | None | ❌ |
| EU Parliament | [European Parliament open data](https://data.europarl.europa.eu/) | JSON | None | ❌ |

**Canada was chosen first** because (a) it's the most common comparator
to US politics in user research, (b) Elections Canada publishes
machine-readable CSVs going back to the 2000s, and (c) its
"House of Commons" maps cleanly to our existing `chamber='house'`
vocabulary, so the adapter is mostly a naming-conversion exercise.

## Schema mapping notes

For each new country we add, two fields matter most on the `politician`
table:

- `country_code` — ISO 3166-1 alpha-2 (`'US'`, `'CA'`, `'GB'`, `'AU'`,
  etc.). Always 2 letters.
- `jurisdiction_level` — `'federal'`, `'state'`, `'provincial'`,
  `'territorial'`, or `'municipal'`. The `chamber` field captures the
  branch of the legislature (e.g. `state_house`, `state_senate`,
  `governor`, `house` for the UK/Canada Commons, `senate`, etc.).

The `state` column is overloaded — for US rows it's the 2-letter
postal code, for Canadian rows it's the 2-letter province code, and
for non-federal/non-state jurisdictions we'll need a follow-up
migration to widen the column or store a separate `region_code`.

## Open follow-ups

1. **Canadian campaign finance** — Elections Canada publishes
   contribution data per candidate, separate from the candidate list.
   Once the candidate catalog is in, a second adapter can ingest
   Canadian `Contribution` rows.
2. **State legislator voting records** — most states don't publish
   roll-call votes in machine-readable form, so this is largely
   out-of-scope. The architecture supports it (the `VotingRecord`
   table is jurisdiction-agnostic) but no source adapter ships in
   Phase 5.
3. **Municipal level** — out of scope; the spec defers it explicitly.
