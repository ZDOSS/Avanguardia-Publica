"""Bounded, read-only reconciliation against the official Senate roll-call XML feed.

This is deliberately a *shadow* source.  It fetches a small current-session window,
matches vote records to the congressional roster exclusively through Senate LIS member
IDs, and reports aggregate alignment with the existing GovTrack feed.  It never creates
people and never writes to ``voting_records``.  A later, separately reviewed source-
provenance migration can use the observed results before making an official source
authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging
import re
import time
from typing import Callable, TypeVar
from xml.etree import ElementTree

import requests
import yaml

from source_health import SourceHealthTracker


logger = logging.getLogger(__name__)

_SENATE_BASE = "https://www.senate.gov/legislative/LIS/roll_call_votes"
_MENU_URL = "https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress}_{session}.htm"
_HISTORICAL_MEMBERS_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/"
    "legislators-historical.yaml"
)
_TIMEOUT_SECONDS = 15
_RETRY_BACKOFF_SECONDS = 0.5
_MAX_CONSECUTIVE_FAILURES = 3
_RECENT_ROLL_CALL_LIMIT = 25
_USER_AGENT = "Avanguardia-Publica ETL senate-roll-call shadow reconciliation"

_MENU_VOTE_RE = re.compile(r"vote_(?P<congress>\d+)_(?P<session>\d+)_(?P<number>\d+)\.htm")
_GOVTRACK_SENATE_LINK_RE = re.compile(
    r"https?://www\.govtrack\.us/congress/votes/"
    r"(?P<congress>\d+)-(?P<year>\d+)/s(?P<number>\d+)",
    re.IGNORECASE,
)

_T = TypeVar("_T")


@dataclass(frozen=True)
class SenateMemberVote:
    """One XML member record; no name is carried into reconciliation logic."""

    lis_member_id: str | None
    vote_cast: str | None


@dataclass(frozen=True)
class SenateRollCall:
    congress: int
    session: int
    congress_year: int
    vote_number: int
    vote_date: str | None
    question: str | None
    source_url: str
    member_votes: tuple[SenateMemberVote, ...]

    @property
    def reconciliation_key(self) -> str:
        """Stable key shared with a Senate GovTrack vote URL when both exist."""
        return f"senate:{self.congress}:{self.congress_year}:{self.vote_number}"


@dataclass
class SenateRollCallShadowReport:
    """Aggregate-only result of one bounded official-source reconciliation pass."""

    roll_calls_listed: int = 0
    roll_calls_fetched: int = 0
    member_votes_seen: int = 0
    member_votes_missing_lis_id: int = 0
    member_votes_missing_vote_cast: int = 0
    exact_lis_matches: int = 0
    unmatched_lis_ids: set[str] = field(default_factory=set)
    historical_lis_ids_loaded: int = 0
    govtrack_vote_cast_matches: int = 0
    govtrack_vote_cast_mismatches: int = 0
    govtrack_vote_not_observed: int = 0

    def counters(self) -> dict[str, int]:
        """ETL summary counters; identifiers and raw vote data stay out of the summary."""
        return {
            "senate_roll_call_shadow_roll_calls_listed": self.roll_calls_listed,
            "senate_roll_call_shadow_roll_calls_fetched": self.roll_calls_fetched,
            "senate_roll_call_shadow_member_votes_seen": self.member_votes_seen,
            "senate_roll_call_shadow_member_votes_missing_lis_id": self.member_votes_missing_lis_id,
            "senate_roll_call_shadow_member_votes_missing_vote_cast": self.member_votes_missing_vote_cast,
            "senate_roll_call_shadow_exact_lis_matches": self.exact_lis_matches,
            "senate_roll_call_shadow_historical_lis_ids_loaded": self.historical_lis_ids_loaded,
            "senate_roll_call_shadow_unmatched_lis_ids": len(self.unmatched_lis_ids),
            "senate_roll_call_shadow_govtrack_vote_cast_matches": self.govtrack_vote_cast_matches,
            "senate_roll_call_shadow_govtrack_vote_cast_mismatches": self.govtrack_vote_cast_mismatches,
            "senate_roll_call_shadow_govtrack_vote_not_observed": self.govtrack_vote_not_observed,
        }

    def description(self) -> str:
        return (
            "Senate XML shadow: "
            f"roll_calls={self.roll_calls_fetched}/{self.roll_calls_listed}, "
            f"exact_lis_matches={self.exact_lis_matches}, "
            f"historical_lis_ids_loaded={self.historical_lis_ids_loaded}, "
            f"unmatched_lis_ids={len(self.unmatched_lis_ids)}, "
            f"govtrack_matches={self.govtrack_vote_cast_matches}, "
            f"govtrack_mismatches={self.govtrack_vote_cast_mismatches}, "
            f"govtrack_not_observed={self.govtrack_vote_not_observed}"
        )


@dataclass
class _FetchState:
    consecutive_failures: int = 0
    breaker_open: bool = False


def _clean(value: str | None) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized or None


def _normalize_lis_id(value: str | None) -> str | None:
    normalized = _clean(value)
    return normalized.upper() if normalized else None


def _current_congress_session(today: date | None = None) -> tuple[int, int]:
    """Return the current Congress and session, handling the Jan. 1-2 transition."""
    current = today or date.today()
    effective_year = current.year
    # A new Congress begins on January 3.  The first two days of January still belong
    # to the prior Congress/session for the Senate's roll-call URL layout.
    if current.month == 1 and current.day < 3:
        effective_year -= 1
    congress = ((effective_year - 1789) // 2) + 1
    session = 1 if effective_year % 2 else 2
    return congress, session


def _roll_call_url(congress: int, session: int, vote_number: int) -> str:
    return (
        f"{_SENATE_BASE}/vote{congress}{session}/"
        f"vote_{congress}_{session}_{vote_number:05d}.xml"
    )


def _parse_menu(text: str, congress: int, session: int) -> list[int]:
    vote_numbers = {
        int(match.group("number"))
        for match in _MENU_VOTE_RE.finditer(text)
        if int(match.group("congress")) == congress
        and int(match.group("session")) == session
    }
    if not vote_numbers:
        raise ValueError("no current-session Senate roll-call links found")
    return sorted(vote_numbers, reverse=True)


def _historical_senate_lis_ids(
    health: SourceHealthTracker | None = None,
) -> set[str]:
    """Load historical Senate LIS IDs from public roster history."""
    if health:
        health.record_attempt()
    started_at = time.monotonic()
    try:
        response = requests.get(
            _HISTORICAL_MEMBERS_URL,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
        status_code = int(getattr(response, "status_code", 0))
        if not 200 <= status_code < 300:
            if health:
                health.record_skip(f"historical_http_{status_code}")
            return set()

        payload = yaml.safe_load(response.text)
        if not isinstance(payload, list):
            raise ValueError("historical legislators payload is not a list")

        lis_ids: set[str] = set()
        for legislator in payload:
            if not isinstance(legislator, dict):
                continue
            terms = legislator.get("terms") or []
            if not isinstance(terms, list):
                continue
            if "sen" not in {
                str((term or {}).get("type") or "").lower()
                for term in terms
                if isinstance(term, dict)
            }:
                continue

            lis_id = str((legislator.get("id") or {}).get("lis") or "").strip()
            if lis_id:
                normalized_lis_id = _normalize_lis_id(lis_id)
                if normalized_lis_id:
                    lis_ids.add(normalized_lis_id)

        if health:
            health.record_success(time.monotonic() - started_at)
        return lis_ids
    except (yaml.YAMLError, ValueError, TypeError) as exc:
        if health:
            health.record_skip("historical_parse_error")
            logger.warning("[Senate XML] Could not parse historical legislators YAML: %s", exc)
        return set()
    except requests.RequestException as exc:
        if health:
            health.record_skip("historical_request_error")
            logger.warning(
                "[Senate XML] Failed to fetch historical legislators YAML: %s",
                exc,
            )
        return set()


def _parse_vote_date(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, "%B %d, %Y, %I:%M %p").date().isoformat()
    except ValueError:
        return None


def _parse_roll_call(
    text: str,
    source_url: str,
    expected_congress: int,
    expected_session: int,
    expected_vote_number: int,
) -> SenateRollCall:
    root = ElementTree.fromstring(text)

    def integer(tag: str) -> int:
        value = _clean(root.findtext(tag))
        if value is None:
            raise ValueError(f"Senate roll-call XML missing {tag}")
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"Senate roll-call XML has invalid {tag}: {value}") from exc

    congress = integer("congress")
    session = integer("session")
    congress_year = integer("congress_year")
    vote_number = integer("vote_number")
    if (congress, session, vote_number) != (
        expected_congress,
        expected_session,
        expected_vote_number,
    ):
        raise ValueError("Senate roll-call XML did not match its requested vote URL")

    member_nodes = root.findall("./members/member")
    if not member_nodes:
        raise ValueError("Senate roll-call XML contains no member votes")
    member_votes = tuple(
        SenateMemberVote(
            lis_member_id=_clean(member.findtext("lis_member_id")),
            vote_cast=_clean(member.findtext("vote_cast")),
        )
        for member in member_nodes
    )
    return SenateRollCall(
        congress=congress,
        session=session,
        congress_year=congress_year,
        vote_number=vote_number,
        vote_date=_parse_vote_date(root.findtext("vote_date")),
        question=_clean(root.findtext("vote_question_text")) or _clean(root.findtext("question")),
        source_url=source_url,
        member_votes=member_votes,
    )


def _fetch_parsed(
    url: str,
    parser: Callable[[str], _T],
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
                    parsed = parser(response.text)
                except (ElementTree.ParseError, ValueError, TypeError) as exc:
                    logger.warning("[Senate XML] Could not parse %s: %s", url, exc)
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
            logger.warning("[Senate XML] Request failed for %s: %s", url, exc)
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


def govtrack_senate_vote_casts(records: list[dict]) -> dict[str, str]:
    """Derive exact reconciliation keys from the authoritative GovTrack vote URL.

    This deliberately refuses to infer a Senate vote from a title, name, or date.  The
    GovTrack URL carries Congress, year, chamber, and roll-call number, which maps to
    the exact same official event identity used by the Senate XML feed.
    """
    by_roll_call: dict[str, str] = {}
    for record in records:
        summary = str(record.get("bill_summary") or "")
        match = _GOVTRACK_SENATE_LINK_RE.search(summary)
        vote_cast = _clean(record.get("vote_cast"))
        if not match or not vote_cast:
            continue
        key = (
            f"senate:{int(match.group('congress'))}:"
            f"{int(match.group('year'))}:{int(match.group('number'))}"
        )
        by_roll_call[key] = vote_cast
    return by_roll_call


def _normalized_vote_cast(value: str) -> str:
    return " ".join(value.lower().split())


def get_recent_senate_roll_call_shadow(
    known_lis_ids: set[str],
    govtrack_votes_by_lis_id: dict[str, dict[str, str]],
    *,
    limit: int = _RECENT_ROLL_CALL_LIMIT,
    health: SourceHealthTracker | None = None,
    today: date | None = None,
) -> SenateRollCallShadowReport:
    """Fetch and reconcile a bounded current Senate session without database writes."""
    report = SenateRollCallShadowReport()
    normalized_govtrack_votes = {
        key: value
        for key, value in (
            (_normalize_lis_id(lis_id), votes)
            for lis_id, votes in govtrack_votes_by_lis_id.items()
        )
        if key
    }
    normalized_lis_ids = {
        normalized
        for lis_id in known_lis_ids
        if (normalized := _normalize_lis_id(lis_id))
    }
    historical_lis_ids = _historical_senate_lis_ids(health=health)
    normalized_lis_ids.update(historical_lis_ids)
    report.historical_lis_ids_loaded = len(historical_lis_ids)
    if not normalized_lis_ids:
        if health:
            health.record_skip("no_lis_join_keys")
        return report

    bounded_limit = max(1, min(int(limit), _RECENT_ROLL_CALL_LIMIT))
    congress, session = _current_congress_session(today)
    state = _FetchState()
    menu_url = _MENU_URL.format(congress=congress, session=session)
    vote_numbers = _fetch_parsed(
        menu_url,
        lambda text: _parse_menu(text, congress, session),
        health=health,
        state=state,
    )
    if not vote_numbers:
        return report

    selected_vote_numbers = vote_numbers[:bounded_limit]
    report.roll_calls_listed = len(selected_vote_numbers)
    for vote_number in selected_vote_numbers:
        source_url = _roll_call_url(congress, session, vote_number)
        roll_call = _fetch_parsed(
            source_url,
            lambda text, source_url=source_url, vote_number=vote_number: _parse_roll_call(
                text,
                source_url,
                congress,
                session,
                vote_number,
            ),
            health=health,
            state=state,
        )
        if roll_call is None:
            if state.breaker_open or (health and health.breaker_tripped):
                break
            continue

        report.roll_calls_fetched += 1
        for member_vote in roll_call.member_votes:
            report.member_votes_seen += 1
            lis_member_id = _normalize_lis_id(member_vote.lis_member_id)
            vote_cast = member_vote.vote_cast
            if not lis_member_id:
                report.member_votes_missing_lis_id += 1
                continue
            if not vote_cast:
                report.member_votes_missing_vote_cast += 1
                continue
            if lis_member_id not in normalized_lis_ids:
                report.unmatched_lis_ids.add(lis_member_id)
                continue

            report.exact_lis_matches += 1
            govtrack_vote_cast = (
                normalized_govtrack_votes.get(lis_member_id, {}).get(
                    roll_call.reconciliation_key
                )
            )
            if not govtrack_vote_cast:
                report.govtrack_vote_not_observed += 1
            elif _normalized_vote_cast(govtrack_vote_cast) == _normalized_vote_cast(vote_cast):
                report.govtrack_vote_cast_matches += 1
            else:
                report.govtrack_vote_cast_mismatches += 1

    return report
