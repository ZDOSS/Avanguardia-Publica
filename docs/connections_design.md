# Cross-Referenced "Connections": Design Note

Companion to [`state_votes_design.md`](state_votes_design.md). Records *what we decided and
why* for the profile **Connections** view — the first feature that cross-references one
individual against others, made possible by the state roll-call votes added in `996c0fc`.

## What we cross-reference

Three connection types, each derived from data we already ingest:

| Connection | Source spoke | Lane | Identity join |
|---|---|---|---|
| **Shared donors** | `campaign_donors` | verified | normalized `donor_name` |
| **Co-voting** allies/opponents | `voting_records` | verified | `roll_call_id` (exact) |
| **Network ties** | `relationships` (LittleSis) | unverified | exact name → `politician_id`, else external |

The first two are official-record-derived and render with the authoritative palette; network
ties are name-matched third-party data and render behind the **Visual Firewall** (gray panel
+ "Third-Party Data - Unverified" badge), per `spec.md` §4A.

Best-practice basis — political networks are conventionally built as *bipartite projections*
(legislator↔legislator via shared bills/donors), surfacing concentrated overlaps worth
scrutiny:
[Cambridge Intelligence](https://cambridge-intelligence.com/visualizing-us-election-campaign-data/),
[ProPublica donor lookup](https://jupiter.propublica.org/look-up-political-donors),
[Poynter](https://www.poynter.org/reporting-editing/2013/how-to-visually-explore-local-politics-with-network-graphs/).

## Decision: compute LIVE, not precomputed

Connections are computed **on demand** by Postgres RPC functions
(`get_shared_donors` / `get_covoting` / `get_network_ties` in
[`migrations/0003_connections.sql`](../migrations/0003_connections.sql)), called
**client-side in the browser** via `supabase.rpc()`
([`frontend/src/lib/connections.ts`](../frontend/src/lib/connections.ts)).

This keeps the `output: "export"` static build on free GitHub Pages: the export ships only
the page *shell*; data is fetched live at view time — exactly how the directory already
works ([`page.tsx`](../frontend/src/app/page.tsx)). No precomputed connections table, no
nightly cross-reference job, no server. The functions are `STABLE SECURITY DEFINER`,
`LIMIT`-bounded, and `EXECUTE`-granted to `anon`, served by indexes on `roll_call_id` and
`lower(btrim(donor_name))`.

## Key realization: co-voting needs a stable roll-call id

`voting_records` previously held only `(bill_name, vote_date)`. `bill_name` like
`"HB 1 — Final Passage"` repeats across all 50 states, so a `(bill_name, vote_date)`
self-join would wrongly match Texas's HB 1 to Florida's HB 1 on the same day. So we added
**`roll_call_id`** — a source-namespaced id for a single roll call
(`openstates:<vote_event_id>` / `govtrack:<vote_id>`) shared by every legislator who voted
on it. Co-voting is then an exact, collision-free self-join on that id. `jurisdiction` rides
along for display.

Both columns are nullable: rows ingested before this change backfill to `NULL` and simply
don't participate in co-voting until re-scraped — no breakage, and the
`(politician_id, bill_name, vote_date)` upsert key is unchanged.

## Network ties: structured relationships

[`littlesis.py`](../scraper/extractors/littlesis.py) previously did only an entity *name
search* into `unconfirmed_mentions`. It now also walks
`/api/entities/{id}/relationships`. That endpoint carries the related entity only as
numeric ids; the name is parsed from the link slug (`/person/13503-Barack_Obama`). Edges land
in the new `relationships` table; `related_politician_id` is filled **only on an exact
full_name match** to a tracked politician (never fuzzy — the loader's identity rule), which
is what lets a tie link to an internal profile instead of out to LittleSis.

## Display

`PoliticianClient` tabs went from `… | Voting | Network & Media` to
`… | Voting | Connections | Media` — connections are now first-class and distinct from the
news feed (which keeps the firewall). The Connections tab
([`ConnectionsTab.tsx`](../frontend/src/app/[politician_id]/ConnectionsTab.tsx)) shows a
hand-rolled SVG hub-and-spoke **mini-graph** (no new dependency; themed via the existing
`--color-*` vars) over ranked **relationship cards**, each card linking to the connected
profile.

## Known limitations / future work

- **Backfill lag** — co-voting populates as the nightly scraper re-ingests votes with
  `roll_call_id`.
- **Donor matching** is exact normalized-name only; FEC name variants under-match. A
  normalized-employer/committee key could improve recall later.
- **OpenSanctions** (approved in `state_votes_design.md`) would slot into the network-ties
  lane the same way once ingested.
