from __future__ import annotations

from collections import defaultdict

from .normalization import identity_keys_from_packet, normalize_identity_name
from .types import (
    ExistingIdentity,
    IdentityKey,
    IdentityPacket,
    IdentityResolution,
    PendingIdentityCandidate,
)


class IdentityResolver:
    """
    First Phase 3 resolver shape.

    This is intentionally pure and deterministic. It does not write database rows yet;
    the loader can adopt it in small slices while preserving the existing legacy
    politicians compatibility path.
    """

    def __init__(self, existing_identities=(), summary=None):
        self.summary = summary
        self._person_ids_by_key: dict[IdentityKey, set[str]] = defaultdict(set)
        self._legacy_ids_by_person_id: dict[str, set[str]] = defaultdict(set)
        for identity in existing_identities:
            self.add_existing_identity(identity)

    def add_existing_identity(self, identity: ExistingIdentity) -> None:
        if identity.legacy_politician_id:
            self._legacy_ids_by_person_id[identity.person_id].add(identity.legacy_politician_id)
        for key in identity.deterministic_keys:
            self._person_ids_by_key[key].add(identity.person_id)

    def resolve(self, packet: IdentityPacket) -> IdentityResolution:
        keys = identity_keys_from_packet(packet)
        if not keys:
            self._increment("identity_pending_candidates")
            return IdentityResolution(
                action="pending_review",
                deterministic_keys=keys,
                legacy_politician_id=packet.legacy_politician_id,
                pending_candidate=PendingIdentityCandidate(
                    candidate_type="missing_deterministic_identity",
                    evidence={
                        "source_system_key": packet.source_system_key,
                        "source_record_key": packet.source_record_key,
                        "normalized_names": [
                            name
                            for name in (
                                normalize_identity_name(value) for value in packet.names
                            )
                            if name
                        ],
                    },
                ),
            )

        matching_person_ids = sorted(
            {
                person_id
                for key in keys
                for person_id in self._person_ids_by_key.get(key, set())
            }
        )

        if len(matching_person_ids) == 1:
            self._increment("identity_deterministic_matches")
            self._increment_legacy_mapping(packet)
            return IdentityResolution(
                action="matched_existing_person",
                deterministic_keys=keys,
                person_id=matching_person_ids[0],
                legacy_politician_id=packet.legacy_politician_id,
            )

        if len(matching_person_ids) > 1:
            self._increment("identity_blocked_conflicts")
            return IdentityResolution(
                action="blocked_conflict",
                deterministic_keys=keys,
                legacy_politician_id=packet.legacy_politician_id,
                blocked_reason="deterministic_keys_match_multiple_people",
            )

        self._increment("identity_people_created")
        self._increment_legacy_mapping(packet)
        return IdentityResolution(
            action="create_person",
            deterministic_keys=keys,
            legacy_politician_id=packet.legacy_politician_id,
        )

    def _increment_legacy_mapping(self, packet: IdentityPacket) -> None:
        if packet.legacy_politician_id:
            self._increment("identity_legacy_rows_mapped")

    def _increment(self, key: str, amount: int = 1) -> None:
        if self.summary:
            self.summary.increment(key, amount)
