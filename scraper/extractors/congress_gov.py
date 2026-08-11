"""Bounded Congress.gov metadata reconciliation for official roll-call measures.

The extractor never lists or crawls Congress.gov collections.  It receives exact bill
and amendment identifiers already present in the bounded House and Senate roll-call XML
snapshots, deduplicates them, and requests only their API v3 detail endpoints.  Results
remain in memory for aggregate shadow reporting; this module does not write the
database, retain raw JSON, or broaden the legacy ``voting_records`` path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import time
from typing import Iterable
from urllib.parse import urlparse

import requests

from source_health import SourceHealthTracker


logger = logging.getLogger(__name__)

_API_BASE = "https://api.congress.gov/v3"
_TIMEOUT_SECONDS = 15
_RETRY_BACKOFF_SECONDS = (0.5,)
_MAX_CONSECUTIVE_FAILURES = 3
_MAX_DISTINCT_REFERENCES = 100
_USER_AGENT = "Avanguardia-Publica ETL bounded Congress.gov metadata shadow"

_BILL_TYPES = frozenset(
    {
        "hr",
        "s",
        "hjres",
        "sjres",
        "hconres",
        "sconres",
        "hres",
        "sres",
    }
)
_AMENDMENT_TYPES = frozenset({"hamdt", "samdt", "suamdt"})
_TYPE_ALIASES = {
    "hr": "hr",
    "housebill": "hr",
    "s": "s",
    "senatebill": "s",
    "hjres": "hjres",
    "housejointresolution": "hjres",
    "sjres": "sjres",
    "senatejointresolution": "sjres",
    "hconres": "hconres",
    "houseconcurrentresolution": "hconres",
    "sconres": "sconres",
    "senateconcurrentresolution": "sconres",
    "hres": "hres",
    "houseresolution": "hres",
    "sres": "sres",
    "senateresolution": "sres",
    "hamdt": "hamdt",
    "houseamendment": "hamdt",
    "samdt": "samdt",
    "senateamendment": "samdt",
    "suamdt": "suamdt",
    "senateunprintedamendment": "suamdt",
}
_PRESENTATION_TYPE_SLUGS = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution",
    "sres": "senate-resolution",
    "hamdt": "house-amendment",
    "samdt": "senate-amendment",
    "suamdt": "senate-amendment",
}


def _clean(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Congress.gov text field is not a string")
    cleaned = " ".join(value.split())
    return cleaned or None


def _compact_measure_type(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z.\s]+", value):
        return None
    compact = re.sub(r"[.\s]", "", value.lower())
    return _TYPE_ALIASES.get(compact)


def _positive_integer(value, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Congress.gov {field_name} is not a positive integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        parsed = int(value)
    else:
        raise ValueError(f"Congress.gov {field_name} is not a positive integer")
    if parsed <= 0:
        raise ValueError(f"Congress.gov {field_name} is not a positive integer")
    return parsed


@dataclass(frozen=True, order=True)
class CongressGovMeasureRef:
    """One exact Congress.gov bill or amendment identity."""

    kind: str
    congress: int
    measure_type: str
    number: int

    def __post_init__(self) -> None:
        expected_types = _BILL_TYPES if self.kind == "bill" else _AMENDMENT_TYPES
        if self.kind not in {"bill", "amendment"}:
            raise ValueError("Congress.gov measure kind must be bill or amendment")
        if self.measure_type not in expected_types:
            raise ValueError("Congress.gov measure type does not match its kind")
        if (
            isinstance(self.congress, bool)
            or not isinstance(self.congress, int)
            or isinstance(self.number, bool)
            or not isinstance(self.number, int)
            or self.congress <= 0
            or self.number <= 0
        ):
            raise ValueError("Congress.gov measure identity must use positive integers")

    @property
    def source_record_key(self) -> str:
        return f"{self.kind}:{self.congress}:{self.measure_type}:{self.number}"

    @property
    def endpoint_path(self) -> str:
        return (
            f"{self.kind}/{self.congress}/{self.measure_type}/{self.number}"
        )

    @property
    def source_url(self) -> str:
        return f"{_API_BASE}/{self.endpoint_path}"

    @property
    def presentation_path(self) -> str:
        type_slug = _PRESENTATION_TYPE_SLUGS[self.measure_type]
        return (
            f"/{self.kind}/{self.congress}th-congress/{type_slug}/{self.number}"
        )


def parse_measure_reference(
    value: str | None,
    *,
    congress: int,
) -> CongressGovMeasureRef | None:
    """Parse a complete official measure label without guessing an identifier.

    Values such as ``H R 8884``, ``S.J.Res. 5``, and ``S.Amdt. 3937`` are
    accepted.  Procedural labels such as ``Amendment No. 12`` and unsupported
    records such as nominations return ``None`` instead of being coerced.
    """

    cleaned = _clean(value)
    if not cleaned or isinstance(congress, bool) or congress <= 0:
        return None
    match = re.fullmatch(r"(?P<type>.*?)[\s.]*(?P<number>[1-9][0-9]*)", cleaned)
    if not match:
        return None
    measure_type = _compact_measure_type(match.group("type"))
    if not measure_type:
        return None
    kind = "bill" if measure_type in _BILL_TYPES else "amendment"
    return CongressGovMeasureRef(
        kind=kind,
        congress=congress,
        measure_type=measure_type,
        number=int(match.group("number")),
    )


@dataclass(frozen=True)
class CongressGovMetadata:
    """Normalized presentation-safe facts from one exact API detail response."""

    reference: CongressGovMeasureRef
    title: str | None
    purpose: str | None
    description: str | None
    origin_chamber: str | None
    introduced_date: str | None
    update_date: str | None
    latest_action_date: str | None
    latest_action_text: str | None
    official_url: str | None
    amended_bill: CongressGovMeasureRef | None
    amended_amendment: CongressGovMeasureRef | None
    source_url: str
    payload_hash: str
    fetched_at: str

    @property
    def has_descriptive_text(self) -> bool:
        return bool(self.title or self.purpose or self.description)


@dataclass
class CongressGovMetadataShadowReport:
    """Aggregate reconciliation plus in-memory normalized metadata candidates."""

    roll_calls_seen: int = 0
    roll_calls_with_supported_references: int = 0
    roll_calls_without_supported_references: int = 0
    roll_calls_with_reference_issues: int = 0
    measure_reference_issues: int = 0
    reference_links_seen: int = 0
    distinct_references: int = 0
    references_fetched: int = 0
    bill_references_fetched: int = 0
    amendment_references_fetched: int = 0
    references_without_descriptive_text: int = 0
    references_not_fetched: int = 0
    metadata: list[CongressGovMetadata] = field(default_factory=list)
    roll_call_keys_by_reference: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    @property
    def complete(self) -> bool:
        return (
            self.distinct_references > 0
            and self.references_fetched == self.distinct_references
            and self.references_not_fetched == 0
        )

    def counters(self) -> dict[str, int]:
        return {
            "congress_gov_metadata_shadow_roll_calls_seen": self.roll_calls_seen,
            "congress_gov_metadata_shadow_roll_calls_with_supported_references": (
                self.roll_calls_with_supported_references
            ),
            "congress_gov_metadata_shadow_roll_calls_without_supported_references": (
                self.roll_calls_without_supported_references
            ),
            "congress_gov_metadata_shadow_roll_calls_with_reference_issues": (
                self.roll_calls_with_reference_issues
            ),
            "congress_gov_metadata_shadow_measure_reference_issues": (
                self.measure_reference_issues
            ),
            "congress_gov_metadata_shadow_reference_links_seen": (
                self.reference_links_seen
            ),
            "congress_gov_metadata_shadow_distinct_references": (
                self.distinct_references
            ),
            "congress_gov_metadata_shadow_references_fetched": (
                self.references_fetched
            ),
            "congress_gov_metadata_shadow_bill_references_fetched": (
                self.bill_references_fetched
            ),
            "congress_gov_metadata_shadow_amendment_references_fetched": (
                self.amendment_references_fetched
            ),
            "congress_gov_metadata_shadow_references_without_descriptive_text": (
                self.references_without_descriptive_text
            ),
            "congress_gov_metadata_shadow_references_not_fetched": (
                self.references_not_fetched
            ),
        }

    def description(self) -> str:
        return (
            "Congress.gov metadata shadow: "
            f"roll_calls_with_refs={self.roll_calls_with_supported_references}/"
            f"{self.roll_calls_seen}, distinct_refs={self.distinct_references}, "
            f"fetched={self.references_fetched}, "
            f"not_fetched={self.references_not_fetched}, "
            f"missing_descriptive_text={self.references_without_descriptive_text}"
        )


@dataclass
class _FetchState:
    consecutive_failures: int = 0
    breaker_open: bool = False


def _official_congress_url(
    value,
    reference: CongressGovMeasureRef,
) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    parsed = urlparse(cleaned)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"congress.gov", "www.congress.gov"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.path.rstrip("/") != reference.presentation_path
    ):
        raise ValueError(
            "Congress.gov response contains a non-official legislation URL"
        )
    return cleaned


def _presentation_url(
    reference: CongressGovMeasureRef,
    detail: dict,
    latest_action: dict,
) -> str | None:
    legislation_url = detail.get("legislationUrl")
    if legislation_url:
        return _official_congress_url(legislation_url, reference)
    links = latest_action.get("links")
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict):
            continue
        candidate = _clean(link.get("url"))
        if not candidate:
            continue
        try:
            return _official_congress_url(candidate, reference)
        except ValueError:
            continue
    return None


def _embedded_reference(
    value,
    *,
    fallback_congress: int,
    expected_kind: str,
) -> CongressGovMeasureRef | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Congress.gov embedded measure reference is not an object")
    congress = value.get("congress", fallback_congress)
    parsed_congress = _positive_integer(congress, "embedded congress")
    measure_type = value.get("type")
    number = value.get("number")
    if not measure_type or number is None:
        raise ValueError("Congress.gov embedded measure reference is incomplete")
    reference = parse_measure_reference(
        f"{measure_type} {number}",
        congress=parsed_congress,
    )
    if reference is None or reference.kind != expected_kind:
        raise ValueError("Congress.gov embedded measure reference is invalid")
    return reference


def _parse_metadata(
    reference: CongressGovMeasureRef,
    raw_content: bytes,
    fetched_at: str,
) -> CongressGovMetadata:
    try:
        payload = json.loads(raw_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Congress.gov detail response is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Congress.gov detail response is not an object")
    detail = payload.get(reference.kind)
    if not isinstance(detail, dict):
        raise ValueError(
            f"Congress.gov detail response is missing its {reference.kind} object"
        )

    response_type = _compact_measure_type(detail.get("type"))
    response_identity = (
        _positive_integer(detail.get("congress"), "congress"),
        response_type,
        _positive_integer(detail.get("number"), "number"),
    )
    if response_identity != (
        reference.congress,
        reference.measure_type,
        reference.number,
    ):
        raise ValueError("Congress.gov detail response identity mismatch")

    latest_action = detail.get("latestAction")
    if not isinstance(latest_action, dict):
        latest_action = {}
    return CongressGovMetadata(
        reference=reference,
        title=_clean(detail.get("title")),
        purpose=_clean(detail.get("purpose")),
        description=_clean(detail.get("description")),
        origin_chamber=_clean(detail.get("originChamber") or detail.get("chamber")),
        introduced_date=_clean(
            detail.get("introducedDate")
            or detail.get("submittedDate")
            or detail.get("proposedDate")
        ),
        update_date=_clean(
            detail.get("updateDateIncludingText") or detail.get("updateDate")
        ),
        latest_action_date=_clean(latest_action.get("actionDate")),
        latest_action_text=_clean(latest_action.get("text")),
        official_url=_presentation_url(reference, detail, latest_action),
        amended_bill=_embedded_reference(
            detail.get("amendedBill"),
            fallback_congress=reference.congress,
            expected_kind="bill",
        ),
        amended_amendment=_embedded_reference(
            detail.get("amendedAmendment"),
            fallback_congress=reference.congress,
            expected_kind="amendment",
        ),
        source_url=reference.source_url,
        payload_hash=hashlib.sha256(raw_content).hexdigest(),
        fetched_at=fetched_at,
    )


def _record_fetch_failure(
    health: SourceHealthTracker | None,
    state: _FetchState,
    reason: str,
    elapsed_seconds: float,
    *,
    hard_failure: bool = False,
) -> None:
    state.consecutive_failures += 1
    if health:
        health.record_failure(reason, elapsed_seconds)
    if hard_failure or state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
        state.breaker_open = True
        if health:
            health.trip_breaker(reason if hard_failure else "consecutive_failures")


def _fetch_metadata(
    reference: CongressGovMeasureRef,
    api_key: str,
    request_get,
    *,
    health: SourceHealthTracker | None,
    state: _FetchState,
) -> CongressGovMetadata | None:
    if state.breaker_open or (health and health.breaker_tripped):
        if health:
            health.record_skip("breaker_open")
        return None

    if health:
        health.record_attempt()
    started_at = time.monotonic()
    failure_reason = "request_error"
    hard_failure = False

    max_attempts = len(_RETRY_BACKOFF_SECONDS) + 1
    for attempt in range(max_attempts):
        try:
            response = request_get(
                reference.source_url,
                params={"api_key": api_key, "format": "json"},
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SECONDS,
            )
            status_code = int(getattr(response, "status_code", 0))
            if status_code == 404:
                if health:
                    health.record_skip("measure_not_available")
                state.consecutive_failures = 0
                return None
            if not 200 <= status_code < 300:
                failure_reason = f"http_{status_code}"
                hard_failure = status_code in (401, 403, 429)
                retryable = status_code >= 500
            else:
                raw_content = getattr(response, "content", None)
                if not isinstance(raw_content, (bytes, bytearray)):
                    raw_content = str(getattr(response, "text", "")).encode("utf-8")
                try:
                    metadata = _parse_metadata(
                        reference,
                        bytes(raw_content),
                        datetime.now(timezone.utc).isoformat(),
                    )
                except (TypeError, ValueError) as exc:
                    failure_reason = (
                        "identity_mismatch"
                        if "identity mismatch" in str(exc)
                        else "invalid_payload"
                    )
                    hard_failure = failure_reason == "identity_mismatch"
                    retryable = False
                    logger.warning(
                        "[Congress.gov] Rejected detail response key=%s reason=%s",
                        reference.source_record_key,
                        failure_reason,
                    )
                else:
                    state.consecutive_failures = 0
                    if health:
                        health.record_success(time.monotonic() - started_at)
                    return metadata
        except requests.RequestException as exc:
            failure_reason = (
                "timeout" if isinstance(exc, requests.Timeout) else "request_error"
            )
            retryable = True
            logger.warning(
                "[Congress.gov] Request failed key=%s attempt=%s/%s reason=%s",
                reference.source_record_key,
                attempt + 1,
                max_attempts,
                failure_reason,
            )

        if retryable and not hard_failure and attempt < max_attempts - 1:
            time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
            continue
        break

    _record_fetch_failure(
        health,
        state,
        failure_reason,
        time.monotonic() - started_at,
        hard_failure=hard_failure,
    )
    return None


def get_roll_call_measure_metadata_shadow(
    roll_calls: Iterable,
    *,
    api_key: str,
    health: SourceHealthTracker | None = None,
    max_distinct_references: int = _MAX_DISTINCT_REFERENCES,
) -> CongressGovMetadataShadowReport:
    """Fetch only exact measure detail records named by bounded roll-call snapshots."""

    normalized_key = str(api_key or "").strip()
    if not normalized_key:
        raise ValueError("Congress.gov API key is required")
    if not 1 <= max_distinct_references <= _MAX_DISTINCT_REFERENCES:
        raise ValueError(
            "Congress.gov reference cap must be between 1 and "
            f"{_MAX_DISTINCT_REFERENCES}"
        )

    report = CongressGovMetadataShadowReport()
    roll_call_keys_by_reference: dict[CongressGovMeasureRef, set[str]] = {}
    for roll_call in roll_calls:
        report.roll_calls_seen += 1
        roll_call_key = str(
            getattr(roll_call, "reconciliation_key", "") or ""
        ).strip()
        roll_call_congress = getattr(roll_call, "congress", None)
        references = tuple(getattr(roll_call, "measure_refs", ()) or ())
        reference_issues = tuple(
            getattr(roll_call, "measure_reference_issues", ()) or ()
        )
        if not roll_call_key:
            raise ValueError("roll call is missing its reconciliation key")
        if any(
            not isinstance(reference, CongressGovMeasureRef)
            for reference in references
        ):
            raise ValueError("roll call contains an invalid Congress.gov reference")
        if any(reference.congress != roll_call_congress for reference in references):
            raise ValueError(
                "roll-call and Congress.gov reference Congress values differ"
            )
        if any(
            not isinstance(issue, str) or not issue.strip()
            for issue in reference_issues
        ):
            raise ValueError("roll call contains an invalid measure-reference issue")
        if reference_issues:
            report.roll_calls_with_reference_issues += 1
            report.measure_reference_issues += len(set(reference_issues))
            if health:
                health.record_skip(
                    "roll_call_reference_issue",
                    len(set(reference_issues)),
                )

        unique_references = set(references)
        if unique_references:
            report.roll_calls_with_supported_references += 1
        else:
            report.roll_calls_without_supported_references += 1
        report.reference_links_seen += len(unique_references)
        for reference in unique_references:
            roll_call_keys_by_reference.setdefault(reference, set()).add(
                roll_call_key
            )

    references = sorted(
        roll_call_keys_by_reference,
        key=lambda reference: reference.source_record_key,
    )
    report.distinct_references = len(references)
    report.roll_call_keys_by_reference = {
        reference.source_record_key: tuple(
            sorted(roll_call_keys_by_reference[reference])
        )
        for reference in references
    }

    if not references:
        if health:
            health.record_skip("no_supported_measure_references")
        return report
    if len(references) > max_distinct_references:
        if health:
            health.record_skip("reference_cap_exceeded", len(references))
            health.trip_breaker("reference_cap_exceeded")
        raise ValueError(
            "Congress.gov reference set exceeds the bounded detail-request cap"
        )

    state = _FetchState()
    session = requests.Session()
    try:
        for index, reference in enumerate(references):
            if state.breaker_open or (health and health.breaker_tripped):
                if health:
                    health.record_skip("breaker_open", len(references) - index)
                break
            metadata = _fetch_metadata(
                reference,
                normalized_key,
                session.get,
                health=health,
                state=state,
            )
            if metadata is None:
                continue
            report.metadata.append(metadata)
            report.references_fetched += 1
            if reference.kind == "bill":
                report.bill_references_fetched += 1
            else:
                report.amendment_references_fetched += 1
            if not metadata.has_descriptive_text:
                report.references_without_descriptive_text += 1
    finally:
        session.close()

    report.references_not_fetched = (
        report.distinct_references - report.references_fetched
    )
    return report
