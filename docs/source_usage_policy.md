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
