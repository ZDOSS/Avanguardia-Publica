"""
crosswalk.py

Identity bridge for state-level sources that do NOT carry an OpenStates `ocd-person`
id (e.g. LegiScan). It turns the openstates/people dataset into in-memory maps from a
shared third-party identifier to the `ocd-person` id we already store in
`politicians.external_ids["openstates"]`:

    LegiScan people  ──votesmart_id──▶  ocd-person  ──▶  politicians.id

OpenStates people YAML records overlapping schemes (`votesmart`, `opensecrets`,
`ballotpedia`, ...) under `other_identifiers`, so the join is a deterministic ID → ID
hop — no fuzzy name matching, matching the loader's identity rule. See
docs/state_votes_design.md for the full rationale and the coverage caveat.

This is keyless and quota-free: it walks the same ~5 MB tarball openstates.py already
downloads — independently, since openstates.py returns *transformed* records, not the
raw person dicts this needs. Pass a `people` iterable of RAW openstates person dicts
(each with `id` + `other_identifiers`) to inject pre-parsed data, e.g. in tests;
otherwise it fetches and parses the tarball itself.
"""

import io
import tarfile
import logging
import requests
import yaml

logger = logging.getLogger(__name__)

# Mirrors openstates.py — the openstates/people repo as a single tarball.
_TARBALL_URL = "https://github.com/openstates/people/archive/refs/heads/main.tar.gz"
_TIMEOUT = 120

# Pivot schemes indexed for bridging, most-trusted first. Vote Smart ids are numeric
# and stable; ballotpedia/opensecrets are fallbacks where Vote Smart is absent. The
# resolve() default order follows this tuple.
_PIVOT_SCHEMES = ("votesmart", "opensecrets", "ballotpedia")

# Schemes whose identifiers are matched case-insensitively (slugs/handles). Numeric
# ids (votesmart, opensecrets) are matched exactly.
_CASE_INSENSITIVE = {"ballotpedia"}


def _norm(scheme: str, identifier) -> str | None:
    """Normalize a raw identifier to its lookup key, or None if unusable."""
    if identifier is None:
        return None
    key = str(identifier).strip()
    if not key:
        return None
    return key.lower() if scheme in _CASE_INSENSITIVE else key


class Crosswalk:
    """
    Maps (scheme, identifier) → ocd-person. Built once, queried many times.

    A pivot id that points to more than one distinct ocd-person is ambiguous and is
    dropped from that scheme's map (recorded in `collisions`) rather than guessing —
    a wrong bridge is worse than a missing one.
    """

    def __init__(self, maps: dict[str, dict[str, str]], collisions: dict[str, int]):
        self._maps = maps
        self.collisions = collisions

    def resolve(self, scheme: str, identifier) -> str | None:
        """ocd-person for a single (scheme, identifier), or None."""
        key = _norm(scheme, identifier)
        if key is None:
            return None
        return self._maps.get(scheme, {}).get(key)

    def resolve_any(self, ids: dict) -> str | None:
        """
        Best-effort ocd-person from a person record carrying several pivot ids
        (e.g. a LegiScan person). Tries pivot schemes in priority order and returns
        the first hit. `ids` keys are scheme names (votesmart, opensecrets, ballotpedia).
        """
        for scheme in _PIVOT_SCHEMES:
            hit = self.resolve(scheme, ids.get(scheme))
            if hit:
                return hit
        return None

    def coverage(self) -> dict[str, int]:
        """Number of resolvable identifiers per scheme — for measuring bridge reach."""
        return {scheme: len(self._maps.get(scheme, {})) for scheme in _PIVOT_SCHEMES}


def _index_person(person: dict, maps: dict, dropped: dict, collisions: dict) -> None:
    """Record this person's pivot ids into `maps`, dropping cross-person collisions."""
    ocd = person.get("id")
    if not ocd:
        return
    for oi in person.get("other_identifiers") or []:
        scheme = oi.get("scheme")
        if scheme not in _PIVOT_SCHEMES:
            continue
        key = _norm(scheme, oi.get("identifier"))
        if key is None:
            continue
        if key in dropped[scheme]:
            # Already known ambiguous (≥2 distinct people) — never re-insert, so a
            # third+ occurrence can't resurrect a dropped key as the last-seen person.
            continue
        prior = maps[scheme].get(key)
        if prior is None:
            maps[scheme][key] = ocd
        elif prior != ocd:
            # Same pivot id mapping to two different people — ambiguous, drop it and
            # remember the key so later occurrences stay out.
            maps[scheme].pop(key, None)
            dropped[scheme].add(key)
            collisions[scheme] = collisions.get(scheme, 0) + 1


def _iter_people(tarball_bytes: bytes):
    """Yield parsed person dicts from the openstates/people tarball bytes."""
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            path = member.name
            if not path.endswith(".yml") or "/data/" not in path:
                continue
            if "/legislature/" not in path and "/executive/" not in path:
                continue
            try:
                f = tar.extractfile(member)
                if f is None:
                    continue
                person = yaml.safe_load(f.read())
                if isinstance(person, dict):
                    yield person
            except Exception as exc:
                logger.warning("[Crosswalk] Failed to parse %s: %s", path, exc)
                continue


def build_crosswalk(people=None) -> Crosswalk:
    """
    Build the pivot-id → ocd-person crosswalk.

    `people` (optional): an iterable of RAW openstates person dicts (each with `id` +
    `other_identifiers`) to inject pre-parsed data, e.g. in tests. If omitted, the
    tarball is fetched and parsed here.
    """
    if people is None:
        print("Building state identity crosswalk from openstates/people...")
        resp = requests.get(_TARBALL_URL, timeout=_TIMEOUT)
        resp.raise_for_status()
        people = _iter_people(resp.content)

    maps: dict[str, dict[str, str]] = {scheme: {} for scheme in _PIVOT_SCHEMES}
    dropped: dict[str, set] = {scheme: set() for scheme in _PIVOT_SCHEMES}
    collisions: dict[str, int] = {}
    for person in people:
        _index_person(person, maps, dropped, collisions)

    xwalk = Crosswalk(maps, collisions)
    cov = xwalk.coverage()
    print(
        "Crosswalk built — resolvable ids: "
        + ", ".join(f"{s}={cov[s]}" for s in _PIVOT_SCHEMES)
        + (f" (dropped {sum(collisions.values())} ambiguous)" if collisions else "")
    )
    return xwalk


if __name__ == "__main__":
    # Smoke test against live data: build the crosswalk and print coverage.
    logging.basicConfig(level=logging.INFO)
    build_crosswalk()
