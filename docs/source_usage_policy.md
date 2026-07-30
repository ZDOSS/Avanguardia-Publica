# Source Usage And Attribution Policy

This policy is the release gate for every external data source. A free API key or an open
endpoint is not, by itself, permission to cache or republish all returned content.

## Required source contract

Before an extractor is enabled in production, record:

- the source-system and endpoint slug;
- whether the source is official, community-maintained, or unverified;
- authentication and quota requirements;
- a stable source record key and fetched URL;
- permitted storage, retention, redistribution, and attribution;
- the person, role, organization, or event key used for attachment;
- source-health thresholds and the behavior when the source is degraded;
- the maintainer review decision in the private source catalog.

Verified facts must attach through trusted identifiers or an explicitly reviewed mapping.
Names may be used for discovery, but never as the sole automatic join for a verified fact.

## Current third-party sources

### Currents

The self-service plans provide headline/API access, but their published pricing terms say
redistribution, republication, long-term caching, and similar publication rights require
separate terms. The scraper therefore stores only the headline, publisher/source label,
and original link unless a maintainer records broader rights in the source catalog.

Source: <https://currentsapi.services/en/product/price>

### NewsData.io

Free-tier results must keep the provider's required attribution. Store only the headline,
source label, original link, and attribution unless separately approved.

Source: <https://newsdata.io/terms-of-service>

### TheNewsAPI

The posted website terms are not clear enough for unattended public redistribution. Keep
this provider disabled in production unless a maintainer records explicit approval and the
app configuration opts in. Development use must still respect the provider's terms.

Source: <https://www.thenewsapi.com/tos>

### GDELT

GDELT datasets permit reuse but require a citation and link to the GDELT Project. Use GDELT
as mention/URL discovery. Do not scrape and republish article bodies from the publishers to
which GDELT links.

Source: <https://www.gdeltproject.org/about.html>

### LittleSis

LittleSis database content is licensed under CC BY-SA 4.0. Keep it in the unverified lane,
display a clear LittleSis attribution and license link, and preserve the original record URL.

Source: <https://littlesis.org/about/terms-of-use/>

## New-source release checklist

An extractor is not production-ready until tests prove that it:

1. cannot create or merge a person from a fuzzy/name-only match;
2. writes a stable source record and provenance reference;
3. creates or updates role terms without flattening person identity;
4. reports attempts, successes, failures, skips, and quota/breaker state;
5. preserves verified and unverified lanes;
6. has a documented retention and attribution decision; and
7. has a rollback or disable path that does not delete historical identity mappings.

### Senate roll-call XML (approved; database-gated, manual runtime opt-in)

The U.S. Senate publishes an [XML record for each roll call](https://www.senate.gov/legislative/LIS/roll_call_votes/)
through the Senate Legislative Information System. The integration fetches at most the 25 most
recent current-session roll calls, matches a member only by the
stable `lis_member_id` crosswalk supplied by `congress-legislators`, and records aggregate
coverage/comparison metrics in the ETL summary. GovTrack comparison is vote-centric: each
available event supplies one complete voter snapshot, joined back to the official LIS member
only through the same roster's trusted LIS-to-Bioguide crosswalk, including historical senators
in the bounded window. A newer official event that GovTrack has not published yet is reported
separately at roll-call and member-vote level instead of looking like a cast conflict. The path
remains bounded to one active roster, one historical roster, one menu, 25 official XML
documents, and at most two GovTrack documents per selected roll call. The same official fetch
retains an in-memory normalized snapshot and raw-byte SHA-256 for the separately gated writer.
It does **not** create people, retain raw XML, write legacy `voting_records`, or expose Senate
XML facts in the public UI.

The corrected comparison ran successfully in both a
[manual production run](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/30418108958)
and the immediately following
[scheduled production run](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/30420913210)
from the same merged code. Across 50 roll calls, they produced 4,996 official member-vote
observations, 4,996 exact LIS matches, zero unmatched LIS IDs, and zero missing
LIS-to-Bioguide crosswalks. All 50 GovTrack event snapshots were available and all 4,996
vote casts agreed, with zero member-level absences or cast conflicts. The bounded Senate
requests succeeded 154 of 154 times, with no failures or skips. Earlier shadow observations
also produced 17,486 exact LIS identity matches and zero cast conflicts; their missing
GovTrack observations were traced to the former active-profile comparison design and
publication timing rather than official-source identity failures.

Migration `0028_senate_roll_call_source_review.sql` therefore marks the catalog source and
endpoint `approved` and reserves `senate-lis` as the official source-record namespace. Its
`wired` repo-fit means only that the bounded read-only extractor exists. It
does **not** enable Senate production writes, add a vote writer, or advance scraper
schema preflight.
Migration `0029` supplied the disabled provenance and conflict-safe database contract.
Migration `0030` supplies the separately reviewed manual-only runtime and database enablement
boundary. Both layers must honor these rules:

- Join the official XML `lis_member_id` through the trusted active-plus-historical
  `congress-legislators` LIS-to-Bioguide crosswalk, then require one exact trusted Bioguide
  owner. Names and office text are not identity keys.
- Use the extractor's stable source-key shape: Congress, calendar year, roll-call number,
  and, for a member vote, the normalized LIS member ID.
- Retain normalized roll-call/member-vote facts, source record ID, fetched URL and time, and
  payload hash. Raw XML is not retained.
- Attribute displayed facts to the
  [United States Senate](https://www.senate.gov/legislative/votes_new.htm) and preserve the
  source link. The Senate's
  [rights policy](https://www.senate.gov/general/privacy.htm) says site information is public
  and may be distributed or copied unless otherwise specified, with appropriate credit.
- Report attempts, successes, failures, skips, and publication lag separately. Any future
  write path must fail closed when the bounded source or exact identity coverage is degraded
  and retain its last valid normalized rows.
- Keep future authoritative writes behind explicit runtime and database disable controls.
  Disabling the shadow fetch or a later writer must not delete review evidence, provenance,
  or identity mappings.

Migration `0029_senate_roll_call_provenance.sql` installs that private storage contract
without enabling ingestion. It reuses the source-record-keyed `legislative_roll_calls` and
`person_roll_call_votes` tables, reserves the canonical Senate event/member-vote namespace,
and installs an owner-only atomic helper. Before any fact mutation, the helper requires one
trusted active Bioguide owner and verifies the supplied LIS-to-Bioguide pair against the
stored `congress-legislators` source record, its source-native profile, and canonical redirect.
It never resolves through a name, party, state, or office field.

The helper rejects stale observations, treats an exact same-timestamp replay as non-mutating
only when the complete normalized parent and active member-vote state still agree, preserves
the last valid vote on an official cast conflict, and retires omitted member provenance
without deleting retained facts. Raw XML remains unstored. At the `0029` boundary, the
public Senate RPC remains a hard preflight-only barrier that cannot call the owner-only helper,
and both catalog write gates are strict JSON `false`; `0030` verifies that exact starting state
before changing it. Migration `0029` also advances schema preflight so deployment drift is
caught before the ETL starts.

Migration `0030_senate_roll_call_production_enablement.sql` verifies that exact disabled
barrier/helper body, owner, security, return, ACL, reverse-dependency, constraint, normalized
Bioguide index, zero-fact, and service-role read-only state. It preserves the public function
OID, replaces only its barrier body with a guarded wrapper, and enables both strict JSON-boolean
database gates in the same transaction. No old-writer drain is required because the prior
public body was never mutating, could not call the helper, and had two false gates. The wrapper
keeps preflight non-mutating and delegates write-shaped payload, exact identity, monotonic,
complete-snapshot, and gate-lock validation to the reviewed owner-only `0029` helper.
`SENATE_ROLL_CALL_WRITE_MODE` remains `disabled` by default, and only manual workflow
dispatches may explicitly select `enabled`. Scheduled and unknown events are hard-disabled
until a successful manual canary and post-canary database audit are reviewed. Disabling the
runtime control or either database gate preserves shadow-only behavior and the last valid rows.

### House Clerk roll-call XML (approved; database-gated, runtime opt-in)

The [Office of the Clerk's roll-call XML](https://clerk.house.gov/evs/) provides an
official record for each House vote. The integration reads at most the 25 most recent
current-session entries from the Clerk's public listing, matches a member only by the XML
`name-id` Bioguide identifier already supplied by `congress-legislators`, and records
aggregate coverage/comparison metrics in the ETL summary. The same fetch now retains an
in-memory normalized snapshot and provenance digest for the private House RPC. Migration
`0027_house_roll_call_production_enablement.sql` enables the reviewed database gate only
after installing a monotonic wrapper, while every scraper run still requires an explicit
runtime opt-in. It does **not** create people, write legacy `voting_records`, retain raw XML,
or expose House Clerk facts in the public UI.

The Phase 4 source review observed five successful 25-roll-call shadow runs
([29673051187](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/29673051187),
[29716133242](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/29716133242),
[29717007354](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/29717007354),
[29800415718](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/29800415718), and
[29868730671](https://github.com/ZDOSS/Avanguardia-Publica/actions/runs/29868730671)). Across
them, the source produced 53,996 member-vote observations, 53,996 exact Bioguide matches,
zero unmatched Bioguide IDs, and zero vote-cast conflicts. The first run contained 25
official votes that were not present in the bounded GovTrack comparison data; later runs
reconciled completely, so those were missing comparison observations rather than conflicts.

Migration `0025_house_roll_call_source_review.sql` therefore marks the catalog source and
endpoint `approved`. Its `wired` repo-fit means the bounded extractor and dormant runtime
path exist; it does **not** enable production vote writes. The authoritative path honors
this contract:

- Join members only by the XML `name-id` Bioguide identifier. Names and office text are not
  identity keys.
- Use the extractor's existing stable source-key shape: Congress, calendar year, roll-call
  number, and (for a member vote) Bioguide ID.
- Treat overlapping listing pages as an incomplete source snapshot, and require parsed
  member-vote category counts to match the Clerk XML's `totals-by-vote` exactly.
- Retain normalized roll-call/member-vote facts, source record ID, fetched URL and time, and
  payload hash. Raw XML is not retained.
- Attribute displayed facts to the
  [Office of the Clerk, U.S. House of Representatives](https://clerk.house.gov/Votes) and
  preserve the source link. The Clerk's
  [rights policy](https://clerk.house.gov/PrivacyPolicy) treats site information as public
  information that may be distributed or copied unless otherwise specified, with citation.
- Report attempts, successes, failures, and skips. When degraded, fail closed for new House
  writes and retain the last valid normalized rows.
- Ship authoritative writes behind an explicit disable control. Disabling them must return
  the extractor to shadow-only operation without deleting provenance or identity mappings.

Migration `0026_house_roll_call_provenance.sql` supplies the private storage and atomic
service-role write contract. It keeps normalized events and member votes in
source-record-keyed tables rather than copying them into legacy public
`voting_records`. Each roll call must resolve every member through one trusted, active
Bioguide owner before the transaction commits, and an existing vote-cast conflict aborts
the whole roll call. Bioguide comparison is case-normalized but still requires exactly one
trusted owner. A later complete snapshot retires provenance for any omitted member vote
without deleting its retained normalized fact. The RPC locks the catalog write-gate rows
for the transaction, so a disable cannot race an in-flight commit. Raw XML remains unstored.

Migration `0027_house_roll_call_production_enablement.sql` preserves the migration `0026`
writer as an owner-only helper and exposes a service-role wrapper that takes the same gate
and per-roll-call locks before checking `fetched_at`. An older observation fails before the
helper is reachable. An exact retry at the stored timestamp returns without mutation only
when its official payload hash, source URL, exact JSONB argument fingerprint, mutable parent
state and controlled metadata, trusted identity owners, and complete active member-vote set
agree in both directions. Before cloning the writer, the migration verifies the exact reviewed
`0026` body, owner, security mode, search path, return contract, effective execute grants, and
zero reverse dependencies. It clones that body to an owner-only helper, replaces the same public
function OID with a fail-closed barrier, closes direct service-role table/column mutations, and
commits with both gates false. It then drains every client transaction that could have observed
the old body, locks the House fact tables, and requires the reviewed zero-fact rollout baseline
before final activation. It requires strict
JSON-boolean gates and case-normalized Bioguide
uniqueness, reduces service-role table/column access to read-only, and preserves only controlled
security-definer mutation paths.
A null-safe House event-prefix namespace
constraint rejects malformed keys and collisions from the generic profile and retirement RPCs
without reserving unrelated Clerk record families. The same transaction then enables both
reviewed database gate rows.
`HOUSE_ROLL_CALL_WRITE_MODE` nevertheless defaults to `disabled` in code and the example
environment. After the successful bounded production canary and post-canary database audit, the
GitHub Actions nightly schedule explicitly selects `enabled` for the same bounded path. Manual
runs retain a required `disabled`/`enabled` choice whose default is `disabled`, and unrecognized
events fail closed. Disabling either the runtime control or either database gate preserves
shadow-only behavior and the last valid rows.
