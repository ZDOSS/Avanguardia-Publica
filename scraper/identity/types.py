from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ResolutionAction = Literal[
    "matched_existing_person",
    "create_person",
    "pending_review",
    "blocked_conflict",
]

IDENTITY_SUMMARY_COUNTERS = (
    "identity_deterministic_matches",
    "identity_people_created",
    "identity_pending_candidates",
    "identity_blocked_conflicts",
    "identity_legacy_rows_mapped",
)


@dataclass(frozen=True, order=True)
class IdentityKey:
    source_system_key: str
    external_id_type: str
    external_id: str


@dataclass(frozen=True)
class IdentityPacket:
    source_system_key: str
    source_record_key: str | None = None
    legacy_politician_id: str | None = None
    source_url: str | None = None
    raw_payload_ref: str | None = None
    source_catalog_slug: str | None = None
    source_endpoint_slug: str | None = None
    payload_hash: str | None = None
    verified_lane: str | None = None
    source_updated_at: Any | None = None
    # ``names`` preserves source display strings. Normalized values live in a
    # separate field so review evidence never loses what the source actually said.
    names: tuple[str, ...] = ()
    normalized_names: tuple[str, ...] = ()
    external_ids: dict[str, Any] = field(default_factory=dict)
    role_facts: dict[str, Any] = field(default_factory=dict)
    spoke_facts: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    review_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExistingIdentity:
    person_id: str
    legacy_politician_id: str | None = None
    deterministic_keys: tuple[IdentityKey, ...] = ()


@dataclass(frozen=True)
class PendingIdentityCandidate:
    candidate_type: str
    evidence: dict[str, Any] = field(default_factory=dict)
    score: float | None = None


@dataclass(frozen=True)
class IdentityResolution:
    action: ResolutionAction
    deterministic_keys: tuple[IdentityKey, ...] = ()
    person_id: str | None = None
    legacy_politician_id: str | None = None
    matching_person_ids: tuple[str, ...] = ()
    legacy_person_ids: tuple[str, ...] = ()
    pending_candidate: PendingIdentityCandidate | None = None
    blocked_reason: str | None = None
