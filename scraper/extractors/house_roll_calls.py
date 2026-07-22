"""Bounded reconciliation and normalized snapshots from official House roll-call XML.

The extractor reads a small current-session window from the House Clerk, joins XML vote
rows to the congressional roster only through the Clerk's ``name-id`` (a Bioguide ID),
and reports aggregate alignment with GovTrack. It also returns the normalized snapshot
and a SHA-256 digest to a separately gated caller. It never creates people, writes
``voting_records``, retains raw XML, or exposes House Clerk facts in the public UI.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
import logging
import re
import time
from typing import Callable, TypeVar
from xml.etree import ElementTree

import requests

from source_health import SourceHealthTracker


logger = logging.getLogger(__name__)

_HOUSE_XML_BASE = "https://clerk.house.gov/evs"
_HOUSE_LIST_URL = "https://clerk.house.gov/Votes/MemberVotes"
_TIMEOUT_SECONDS = 15
_RETRY_BACKOFF_SECONDS = 0.5
_MAX_CONSECUTIVE_FAILURES = 3
_RECENT_ROLL_CALL_LIMIT = 25
_LIST_PAGE_SIZE = 10
_USER_AGENT = "Avanguardia-Publica ETL house-roll-call reconciliation"

_HOUSE_VOTE_PATH_RE = re.compile(
    r"/Votes/(?P<year>\d{4})(?P<number>\d+)(?=[\"'&?<#\s]|$)"
)
_GOVTRACK_HOUSE_LINK_RE = re.compile(
    r"https?://www\.govtrack\.us/congress/votes/"
    r"(?P<congress>\d+)-(?P<year>\d+)/h(?P<number>\d+)",
    re.IGNORECASE,
)
_HOUSE_SESSION_VALUES = {"1st": 1, "2nd": 2}

_T = TypeVar("_T")


@dataclass(frozen=True)
class HouseMemberVote:
    """One official XML member vote, joined only by its Bioguide identifier."""

    bioguide_id: str | None
    vote_cast: str | None


@dataclass(frozen=True)
class HouseRollCall:
    congress: int
    session: int
    congress_year: int
    vote_number: int
    vote_date: str | None
    question: str | None
    source_url: str
    member_votes: tuple[HouseMemberVote, ...]
    vote_result: str | None = None
    payload_hash: str | None = None
    fetched_at: str | None = None
    official_member_vote_total: int | None = None

    @property
    def reconciliation_key(self) -> str:
        """Stable key shared with a House GovTrack vote URL when both exist."""
        return f"house:{self.congress}:{self.congress_year}:{self.vote_number}"

    def rpc_payload(self) -> tuple[dict, list[dict]]:
        """Build the reviewed migration-0026 payload without retaining raw XML."""
        required_values = (
            self.vote_date,
            self.question,
            self.source_url,
            self.payload_hash,
            self.fetched_at,
        )
        if any(not value for value in required_values):
            raise ValueError("House roll call is missing required write provenance")
        if not re.fullmatch(r"[0-9a-f]{64}", self.payload_hash or ""):
            raise ValueError("House roll call payload hash is not a SHA-256 digest")
        if self.official_member_vote_total != len(self.member_votes):
            raise ValueError(
                "House roll call member rows do not match the official vote total"
            )

        member_payloads = []
        seen_bioguide_ids = set()
        for member_vote in self.member_votes:
            bioguide_id = _normalize_bioguide_id(member_vote.bioguide_id)
            vote_cast = _canonical_vote_cast(member_vote.vote_cast)
            if not bioguide_id or not re.fullmatch(r"[A-Z][0-9]{6}", bioguide_id):
                raise ValueError("House roll call contains an invalid Bioguide ID")
            if bioguide_id in seen_bioguide_ids:
                raise ValueError("House roll call contains duplicate Bioguide IDs")
            if not vote_cast:
                raise ValueError("House roll call contains an unsupported vote cast")
            seen_bioguide_ids.add(bioguide_id)
            member_payloads.append(
                {
                    "source_record_key": f"{self.reconciliation_key}:{bioguide_id}",
                    "bioguide_id": bioguide_id,
                    "vote_cast": vote_cast,
                }
            )
        if not member_payloads:
            raise ValueError("House roll call contains no member votes")

        roll_call_payload = {
            "source_record_key": self.reconciliation_key,
            "congress": self.congress,
            "session": self.session,
            "congress_year": self.congress_year,
            "roll_call_number": self.vote_number,
            "vote_date": self.vote_date,
            "question": self.question,
            "vote_result": self.vote_result,
            "source_url": self.source_url,
            "payload_hash": self.payload_hash,
            "fetched_at": self.fetched_at,
        }
        return roll_call_payload, sorted(
            member_payloads, key=lambda item: item["bioguide_id"]
        )


@dataclass
class HouseRollCallShadowReport:
    """Bounded reconciliation result with normalized candidates and aggregate metrics."""

    roll_calls_listed: int = 0
    roll_calls_fetched: int = 0
    member_votes_seen: int = 0
    member_votes_missing_bioguide_id: int = 0
    member_votes_missing_vote_cast: int = 0
    exact_bioguide_matches: int = 0
    unmatched_bioguide_ids: set[str] = field(default_factory=set)
    govtrack_vote_cast_matches: int = 0
    govtrack_vote_cast_mismatches: int = 0
    govtrack_vote_not_observed: int = 0
    listing_complete: bool = False
    roll_calls: list[HouseRollCall] = field(default_factory=list)

    @property
    def snapshot_complete(self) -> bool:
        return (
            self.listing_complete
            and self.roll_calls_fetched == self.roll_calls_listed
            and len(self.roll_calls) == self.roll_calls_fetched
        )

    def authoritative_write_block_reasons(
        self, health: SourceHealthTracker | None = None
    ) -> tuple[str, ...]:
        """Aggregate-only reasons that prevent the bounded snapshot from being written."""
        reasons = []
        if not self.snapshot_complete:
            reasons.append("incomplete_snapshot")
        if self.member_votes_missing_bioguide_id:
            reasons.append("missing_bioguide_ids")
        if self.member_votes_missing_vote_cast:
            reasons.append("missing_vote_casts")
        if self.unmatched_bioguide_ids:
            reasons.append("unmatched_bioguide_ids")
        if self.govtrack_vote_cast_mismatches:
            reasons.append("reconciliation_mismatches")
        if self.govtrack_vote_not_observed:
            reasons.append("reconciliation_not_observed")
        if health and health.status != "healthy":
            reasons.append("source_health_not_healthy")
        try:
            for roll_call in self.roll_calls:
                roll_call.rpc_payload()
        except ValueError:
            reasons.append("invalid_write_payload")
        return tuple(reasons)

    def counters(self) -> dict[str, int]:
        """ETL summary counters; identifiers and raw vote data stay out of the summary."""
        return {
            "house_roll_call_shadow_roll_calls_listed": self.roll_calls_listed,
            "house_roll_call_shadow_roll_calls_fetched": self.roll_calls_fetched,
            "house_roll_call_shadow_member_votes_seen": self.member_votes_seen,
            "house_roll_call_shadow_member_votes_missing_bioguide_id": (
                self.member_votes_missing_bioguide_id
            ),
            "house_roll_call_shadow_member_votes_missing_vote_cast": (
                self.member_votes_missing_vote_cast
            ),
            "house_roll_call_shadow_exact_bioguide_matches": (
                self.exact_bioguide_matches
            ),
            "house_roll_call_shadow_unmatched_bioguide_ids": len(
                self.unmatched_bioguide_ids
            ),
            "house_roll_call_shadow_govtrack_vote_cast_matches": (
                self.govtrack_vote_cast_matches
            ),
            "house_roll_call_shadow_govtrack_vote_cast_mismatches": (
                self.govtrack_vote_cast_mismatches
            ),
            "house_roll_call_shadow_govtrack_vote_not_observed": (
                self.govtrack_vote_not_observed
            ),
        }

    def description(self) -> str:
        return (
            "House XML shadow: "
            f"roll_calls={self.roll_calls_fetched}/{self.roll_calls_listed}, "
            f"exact_bioguide_matches={self.exact_bioguide_matches}, "
            f"unmatched_bioguide_ids={len(self.unmatched_bioguide_ids)}, "
            f"govtrack_matches={self.govtrack_vote_cast_matches}, "
            f"govtrack_mismatches={self.govtrack_vote_cast_mismatches}, "
            f"govtrack_not_observed={self.govtrack_vote_not_observed}"
        )


@dataclass
class _FetchState:
    consecutive_failures: int = 0
    breaker_open: bool = False


@dataclass(frozen=True)
class _FetchedDocument:
    text: str
    content: bytes
    payload_hash: str
    fetched_at: str


def _clean(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def _normalize_bioguide_id(value: str | None) -> str | None:
    normalized = _clean(value)
    return normalized.upper() if normalized else None


def _current_congress_session(today: date | None = None) -> tuple[int, int, int]:
    """Return the active Congress/session and its House XML calendar year."""
    current = today or date.today()
    effective_year = current.year
    # A new Congress begins on January 3. The first two days of January still use
    # the prior Congress/session in the official vote layout.
    if current.month == 1 and current.day < 3:
        effective_year -= 1
    congress = ((effective_year - 1789) // 2) + 1
    session = 1 if effective_year % 2 else 2
    return congress, session, effective_year


def _member_votes_url(congress: int, session: int, page: int) -> str:
    session_suffix = "st" if session == 1 else "nd"
    return (
        f"{_HOUSE_LIST_URL}?Page={page}&CongressNum={congress}"
        f"&Session={session}{session_suffix}"
    )


def _roll_call_url(year: int, vote_number: int) -> str:
    return f"{_HOUSE_XML_BASE}/{year}/roll{vote_number:03d}.xml"


def _parse_member_votes_page(text: str, expected_year: int) -> list[tuple[int, int]]:
    """Read only official current-session vote paths from the Clerk's listing HTML."""
    vote_keys = {
        (int(match.group("year")), int(match.group("number")))
        for match in _HOUSE_VOTE_PATH_RE.finditer(text)
        if int(match.group("year")) == expected_year
    }
    empty_listing = re.search(
        r"\b(?:0\s+Results|No\s+Votes?\s+Found)\b", text, re.IGNORECASE
    )
    if not vote_keys and not empty_listing:
        raise ValueError("no current-session House roll-call links found")
    return sorted(vote_keys, reverse=True)


def _parse_vote_date(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    for date_format in ("%d-%b-%Y", "%d-%B-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_roll_call(
    text: str | bytes,
    source_url: str,
    expected_congress: int,
    expected_session: int,
    expected_year: int,
    expected_vote_number: int,
    *,
    payload_hash: str | None = None,
    fetched_at: str | None = None,
) -> HouseRollCall:
    root = ElementTree.fromstring(text)
    metadata = root.find("vote-metadata")
    if metadata is None:
        raise ValueError("House roll-call XML missing vote metadata")

    def integer(tag: str) -> int:
        value = _clean(metadata.findtext(tag))
        if value is None:
            raise ValueError(f"House roll-call XML missing {tag}")
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"House roll-call XML has invalid {tag}: {value}") from exc

    congress = integer("congress")
    vote_number = integer("rollcall-num")
    session = _HOUSE_SESSION_VALUES.get(
        (_clean(metadata.findtext("session")) or "").lower()
    )
    if session is None:
        raise ValueError("House roll-call XML has invalid session")
    if (congress, session, vote_number) != (
        expected_congress,
        expected_session,
        expected_vote_number,
    ):
        raise ValueError("House roll-call XML did not match its requested vote URL")

    vote_date = _parse_vote_date(metadata.findtext("action-date"))
    if vote_date and int(vote_date[:4]) != expected_year:
        raise ValueError("House roll-call XML did not match its requested calendar year")

    member_nodes = root.findall("./vote-data/recorded-vote")
    if not member_nodes:
        raise ValueError("House roll-call XML contains no member votes")

    def member_vote(member) -> HouseMemberVote:
        legislator = member.find("legislator")
        return HouseMemberVote(
            bioguide_id=_clean(
                legislator.get("name-id") if legislator is not None else None
            ),
            vote_cast=_clean(member.findtext("vote")),
        )

    member_votes = tuple(member_vote(member) for member in member_nodes)
    totals_by_vote = metadata.find("./vote-totals/totals-by-vote")
    if totals_by_vote is None:
        raise ValueError("House roll-call XML missing official vote totals")

    total_tags = {
        "yea": "yea-total",
        "nay": "nay-total",
        "present": "present-total",
        "not_voting": "not-voting-total",
    }
    official_vote_totals = {}
    for vote_cast, tag in total_tags.items():
        raw_total = _clean(totals_by_vote.findtext(tag))
        try:
            total = int(raw_total or "")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"House roll-call XML has an invalid {tag}") from exc
        if total < 0:
            raise ValueError(f"House roll-call XML has a negative {tag}")
        official_vote_totals[vote_cast] = total

    parsed_vote_totals = Counter()
    for parsed_member_vote in member_votes:
        canonical_vote_cast = _canonical_vote_cast(parsed_member_vote.vote_cast)
        if canonical_vote_cast is None:
            raise ValueError("House roll-call XML has an unsupported member vote cast")
        parsed_vote_totals[canonical_vote_cast] += 1
    if any(
        parsed_vote_totals[vote_cast] != expected_total
        for vote_cast, expected_total in official_vote_totals.items()
    ):
        raise ValueError("House roll-call member votes do not match official vote totals")

    return HouseRollCall(
        congress=congress,
        session=session,
        congress_year=expected_year,
        vote_number=vote_number,
        vote_date=vote_date,
        question=_clean(metadata.findtext("vote-question"))
        or _clean(metadata.findtext("vote-desc")),
        source_url=source_url,
        member_votes=member_votes,
        vote_result=_clean(metadata.findtext("vote-result")),
        payload_hash=payload_hash,
        fetched_at=fetched_at,
        official_member_vote_total=sum(official_vote_totals.values()),
    )


def _fetch_parsed(
    url: str,
    parser: Callable[[_FetchedDocument], _T],
    *,
    health: SourceHealthTracker | None,
    state: _FetchState,
) -> _T | None:
    """Fetch one public document with one retry and source-health accounting."""
    if state.breaker_open or (health and health.breaker_tripped):
        if health:
            health.record_skip("breaker_open")
        return None

    if health:
        health.record_attempt()
    started_at = time.monotonic()
    failure_reason = "request_error"
    hard_failure = False

    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SECONDS,
            )
            status_code = int(getattr(response, "status_code", 0))
            if not 200 <= status_code < 300:
                failure_reason = f"http_{status_code}"
                hard_failure = status_code in (401, 403, 429)
                retryable = status_code >= 500
            else:
                try:
                    raw_content = getattr(response, "content", None)
                    if not isinstance(raw_content, (bytes, bytearray)):
                        raw_content = str(response.text).encode("utf-8")
                    document = _FetchedDocument(
                        text=response.text,
                        content=bytes(raw_content),
                        payload_hash=hashlib.sha256(bytes(raw_content)).hexdigest(),
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                    parsed = parser(document)
                except (ElementTree.ParseError, ValueError, TypeError) as exc:
                    logger.warning("[House XML] Could not parse %s: %s", url, exc)
                    failure_reason = "parse_error"
                    retryable = False
                else:
                    state.consecutive_failures = 0
                    if health:
                        health.record_success(time.monotonic() - started_at)
                    return parsed
        except requests.Timeout:
            failure_reason = "timeout"
            retryable = True
        except requests.RequestException as exc:
            logger.warning("[House XML] Request failed for %s: %s", url, exc)
            failure_reason = "request_error"
            retryable = True

        if retryable and attempt == 0 and not hard_failure:
            time.sleep(_RETRY_BACKOFF_SECONDS)
            continue
        break

    state.consecutive_failures += 1
    if health:
        health.record_failure(failure_reason, time.monotonic() - started_at)
        if hard_failure:
            health.trip_breaker(failure_reason)
    if hard_failure or state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        state.breaker_open = True
        if health:
            health.trip_breaker(
                failure_reason if hard_failure else "consecutive_failures"
            )
    return None


def govtrack_house_vote_casts(records: list[dict]) -> dict[str, str]:
    """Derive exact reconciliation keys from authoritative House GovTrack URLs."""
    by_roll_call: dict[str, str] = {}
    for record in records:
        summary = str(record.get("bill_summary") or "")
        match = _GOVTRACK_HOUSE_LINK_RE.search(summary)
        vote_cast = _clean(record.get("vote_cast"))
        if not match or not vote_cast:
            continue
        key = (
            f"house:{int(match.group('congress'))}:"
            f"{int(match.group('year'))}:{int(match.group('number'))}"
        )
        by_roll_call[key] = vote_cast
    return by_roll_call


def _canonical_vote_cast(value: str | None) -> str | None:
    normalized = " ".join((value or "").lower().replace("_", " ").split())
    canonical = {
        "aye": "yea",
        "yes": "yea",
        "yea": "yea",
        "no": "nay",
        "nay": "nay",
        "present": "present",
        "not voting": "not_voting",
    }.get(normalized)
    return canonical


def _normalized_vote_cast(value: str) -> str:
    return _canonical_vote_cast(value) or " ".join(value.lower().split())


def get_recent_house_roll_call_shadow(
    known_bioguide_ids: set[str],
    govtrack_votes_by_bioguide_id: dict[str, dict[str, str]],
    *,
    limit: int = _RECENT_ROLL_CALL_LIMIT,
    health: SourceHealthTracker | None = None,
    today: date | None = None,
) -> HouseRollCallShadowReport:
    """Fetch and reconcile a bounded current House session without database writes."""
    report = HouseRollCallShadowReport()
    normalized_govtrack_votes = {}
    for bioguide_id, vote_map in govtrack_votes_by_bioguide_id.items():
        normalized_bioguide_id = _normalize_bioguide_id(bioguide_id)
        if normalized_bioguide_id and isinstance(vote_map, dict):
            normalized_govtrack_votes[normalized_bioguide_id] = vote_map
    normalized_bioguide_ids = {
        normalized
        for bioguide_id in known_bioguide_ids
        if (normalized := _normalize_bioguide_id(bioguide_id))
    }
    if not normalized_bioguide_ids:
        if health:
            health.record_skip("no_bioguide_join_keys")
        return report

    bounded_limit = max(1, min(int(limit), _RECENT_ROLL_CALL_LIMIT))
    congress, session, current_year = _current_congress_session(today)
    state = _FetchState()
    listed_roll_calls: set[tuple[int, int]] = set()
    page_count = (bounded_limit + _LIST_PAGE_SIZE - 1) // _LIST_PAGE_SIZE
    listing_failed = False

    for page in range(1, page_count + 1):
        listed_on_page = _fetch_parsed(
            _member_votes_url(congress, session, page),
            lambda document: _parse_member_votes_page(document.text, current_year),
            health=health,
            state=state,
        )
        if listed_on_page is None:
            listing_failed = True
            break
        if not listed_on_page:
            if page == 1 and health:
                health.record_skip("no_current_session_roll_calls")
            break
        duplicate_listing_entries = listed_roll_calls.intersection(listed_on_page)
        if duplicate_listing_entries:
            if health:
                health.record_skip(
                    "duplicate_listing_entry", len(duplicate_listing_entries)
                )
            listing_failed = True
            break
        listed_roll_calls.update(listed_on_page)
        if len(listed_roll_calls) >= bounded_limit:
            break

    report.listing_complete = not listing_failed
    if listing_failed:
        report.roll_calls_listed = min(len(listed_roll_calls), bounded_limit)
        return report

    selected_roll_calls = sorted(listed_roll_calls, reverse=True)[:bounded_limit]
    report.roll_calls_listed = len(selected_roll_calls)
    for vote_year, vote_number in selected_roll_calls:
        source_url = _roll_call_url(vote_year, vote_number)
        roll_call = _fetch_parsed(
            source_url,
            lambda document, source_url=source_url, vote_year=vote_year, vote_number=vote_number: (
                _parse_roll_call(
                    document.content,
                    source_url,
                    congress,
                    session,
                    vote_year,
                    vote_number,
                    payload_hash=document.payload_hash,
                    fetched_at=document.fetched_at,
                )
            ),
            health=health,
            state=state,
        )
        if roll_call is None:
            if state.breaker_open or (health and health.breaker_tripped):
                break
            continue

        report.roll_calls_fetched += 1
        report.roll_calls.append(roll_call)
        for member_vote in roll_call.member_votes:
            report.member_votes_seen += 1
            bioguide_id = _normalize_bioguide_id(member_vote.bioguide_id)
            vote_cast = member_vote.vote_cast
            if not bioguide_id:
                report.member_votes_missing_bioguide_id += 1
                continue
            if not vote_cast:
                report.member_votes_missing_vote_cast += 1
                continue
            if bioguide_id not in normalized_bioguide_ids:
                report.unmatched_bioguide_ids.add(bioguide_id)
                continue

            report.exact_bioguide_matches += 1
            govtrack_vote_cast = normalized_govtrack_votes.get(bioguide_id, {}).get(
                roll_call.reconciliation_key
            )
            if not govtrack_vote_cast:
                report.govtrack_vote_not_observed += 1
            elif _normalized_vote_cast(govtrack_vote_cast) == _normalized_vote_cast(
                vote_cast
            ):
                report.govtrack_vote_cast_matches += 1
            else:
                report.govtrack_vote_cast_mismatches += 1

    return report
