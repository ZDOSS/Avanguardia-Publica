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

### Senate roll-call XML (shadow candidate)

The U.S. Senate publishes an [XML record for each roll call](https://www.senate.gov/legislative/LIS/roll_call_votes/)
through the Senate Legislative Information System. The initial integration is deliberately read-only: it fetches at most
the 25 most recent current-session roll calls, matches a member only by the stable
`lis_member_id` crosswalk already supplied by `congress-legislators`, and records aggregate
coverage/comparison metrics in the ETL summary. It does **not** create people, write vote
rows, retain raw XML, or expose Senate XML facts in the public UI.

The catalog source and endpoint remain `candidate` during this shadow phase. A later
authoritative ingestion change must first review the observed metrics, record source
provenance and retention/attribution decisions, and add a conflict-safe vote storage path.

### House Clerk roll-call XML (approved; writes disabled)

The [Office of the Clerk's roll-call XML](https://clerk.house.gov/evs/) provides an
official record for each House vote. The initial integration is deliberately read-only: it
reads at most the 25 most recent current-session entries from the Clerk's public listing,
matches a member only by the XML `name-id` Bioguide identifier already supplied by
`congress-legislators`, and records aggregate coverage/comparison metrics in the ETL
summary. It does **not** create people, write vote rows, retain raw XML, or expose House
Clerk facts in the public UI.

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
endpoint `approved`. Its `wired` repo-fit means the bounded shadow extractor exists; it
does **not** enable production vote writes. The separate authoritative-ingestion PR must
honor this contract:

- Join members only by the XML `name-id` Bioguide identifier. Names and office text are not
  identity keys.
- Use the extractor's existing stable source-key shape: Congress, calendar year, roll-call
  number, and (for a member vote) Bioguide ID.
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
