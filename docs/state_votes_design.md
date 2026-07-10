# State-Level Voting Records: Source Evaluation & Identity Bridge

Design note for extending the scraper beyond federal roll-call votes. The active source
inventory and implementation order now live in
[`canonical_data_and_analytics_plan.md`](canonical_data_and_analytics_plan.md). This note
records the state-vote decision and its identity tradeoffs.

## Where we are today

The pipeline already ingests, keyed by **stable IDs in `politicians.external_ids`**
(never fuzzy names — see `loader.py`):

| Source | Spoke | Identity key |
|---|---|---|
| congress-legislators (YAML) | hub + contact | `bioguide_id`, crosswalk |
| OpenFEC | `campaign_donors` (verified) | `external_ids["fec"]` |
| GovTrack | `voting_records` (verified) | `external_ids["govtrack"]` |
| openstates/people (tarball) | hub + contact | `external_ids["openstates"]` (`ocd-person`) |
| federal exec/judicial | hub + contact | `external_ids["wikidata"]` |
| LittleSis, news | `unconfirmed_mentions` | name (unverified lane) |

OpenStates roll-call ingestion is now implemented. The remaining reliability work is to
report source coverage/failures explicitly and to retain source-record provenance for each
vote instead of treating an empty extractor response as success.

## Decision: fill state votes; the two viable sources

Three new sources were evaluated (full notes in the companion doc). For state votes:

- **OpenStates API v3** — votes reference legislators by the **same `ocd-person` id
  we already store**, so identity is free (no bridge). *But* the free tier is
  **500 queries/day, 10/min**. That cannot cover 8,000 legislators per-person nightly.
- **LegiScan** — free tier is **30,000 queries/month (~1,000/day)**, materially more
  headroom. *But* it has no `ocd-person`; identity must be bridged (below).

### Key realization: ingest by roll-call, not by person

Both state APIs are fundamentally **bill / roll-call-centric**. One roll-call request
returns *how every legislator voted on that bill* — often 100+ people at once. That
fans out far more efficiently than the federal per-person GovTrack pattern: we pull a
bounded window of recent roll-calls per state and distribute each voter to our hub,
rather than issuing one request per politician. This is what makes either source fit
inside the quota.

## The identity bridge (answers the "how do we tie this to the crosswalk" question)

### OpenStates API → hub: no bridge needed

The API's vote rolls carry `voter_id = ocd-person`, which is exactly
`external_ids["openstates"]`. Join directly on the row we already have.

### LegiScan → hub: bridge via a shared third-party ID

LegiScan's person object exposes `votesmart_id`, `opensecrets_id`, `ballotpedia`,
`knowwho_pid`, `ftm_eid` — but **no `ocd-person`**. OpenStates people YAML stores the
overlapping schemes (`votesmart`, `opensecrets`, `ballotpedia`, `fec`) under
`other_identifiers`, alongside the `ocd-person` id. So the join path is a deterministic
**ID → ID** hop (not name matching — satisfies the loader's design rule):

```
LegiScan people_id
  └─ votesmart_id ──match──▶ OpenStates other_identifiers[scheme=votesmart]
        └─ ocd-person ──▶ politicians.external_ids["openstates"] ──▶ politicians.id
```

- **Vote Smart ID is the primary pivot** — numeric, stable, present on both sides.
- `ballotpedia` slug and `opensecrets` id are fallback pivots where Vote Smart is absent.

### Built from the tarball we already download — zero extra quota

`openstates.py` already pulls the full people tarball (~5 MB) once per run. The bridge
is just a second pass over that same data, producing in-memory maps
`{scheme: {identifier → ocd-person}}`. No API calls, fully deterministic, unit-testable
offline. Implemented in `extractors/crosswalk.py`.

### MEASURED RESULT: the LegiScan bridge is not viable today

`crosswalk.py` was run against live openstates/people data (8,197 people). The pivot
ids exist almost entirely for **federal** members, not state legislators:

| Pivot scheme | Resolvable ids | Federal (has bioguide) | **State legislators** |
|---|---|---|---|
| votesmart | 498 | 432 | **66** (almost all Arkansas) |
| opensecrets | 451 | ~federal-dominated | ~0 |
| ballotpedia | 473 | ~federal-dominated | ~0 |

So Vote Smart / OpenSecrets / Ballotpedia are populated for the ~535 Congress members
OpenStates also tracks (which we already key via `bioguide`/`govtrack`), and for
essentially no one else. A LegiScan bridge through these pivots would resolve **~1% of
state legislators** — a dead end.

**Consequence:** LegiScan is shelved. **OpenStates API v3 is the path for state votes**,
because its vote rolls carry `ocd-person` directly — no bridge needed, so this whole
coverage problem disappears. The `crosswalk.py` module is retained as a tested,
reusable diagnostic (and would serve any *future* pivot-carrying source), but is not on
the state-vote critical path.

## Sources also approved (separate work)

- **OpenSanctions** — PEP / entity-relationship data, complements LittleSis in the
  `unconfirmed_mentions` lane (or promoted where it carries a Wikidata QID). Bulk
  JSON/CSV; low risk, touches no verified spoke. Tracked separately.

## Rejected / out of scope for the state-vote extractor

- **Google Civic Information API** — the representatives/officials-by-address endpoints
  were sunset by Google (~April 2025); the feature it was pitched for no longer exists.
- **Congress.gov API and GovInfo** — not state-vote sources. They remain approved candidates
  in the canonical roadmap for official federal bill, committee, document, and roll-call
  reconciliation after source-record provenance is in place.

## Build order

1. **`extractors/crosswalk.py`** — identity-bridge diagnostic from the tarball; used to
   measure pivot coverage (above). Retained, but off the state-vote critical path. *(done)*
2. **`extractors/openstates_votes.py`** — bill/roll-call-centric vote ingestion via
   OpenStates API v3, joined on `ocd-person`, landing in `voting_records`. Gated on a
   free `OPENSTATES_API_KEY` (skipped when absent, like `FEC_API_KEY`); per-run request
   budget + circuit breaker + 10 req/min pacing tuned to the 500/day quota, crawling a
   rolling 30-day window of recently-updated bills per state (50 states + DC). Wired
   into `main.py`: the state-people loop builds an `ocd-person → politician_id` map,
   and votes are fanned out onto it. *(done)*
