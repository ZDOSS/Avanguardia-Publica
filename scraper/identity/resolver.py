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
    Pure, deterministic Phase 3 pre-write resolver.

    The loader runs this resolver before the transactional source-profile RPC. The
    resolver never mutates storage itself: deterministic conflicts and name-only
    packets are blocked for review before compatibility or canonical rows can change.
    """

    def __init__(self, existing_identities=(), summary=None):
        self.summary = summary
        self._person_ids_by_key: dict[IdentityKey, set[str]] = defaultdict(set)
        self._legacy_ids_by_person_id: dict[str, set[str]] = defaultdict(set)
        self._person_ids_by_legacy_id: dict[str, set[str]] = defaultdict(set)
        for identity in existing_identities:
            self.add_existing_identity(identity)

    def add_existing_identity(self, identity: ExistingIdentity) -> None:
        if identity.legacy_politician_id:
            self._legacy_ids_by_person_id[identity.person_id].add(identity.legacy_politician_id)
            self._person_ids_by_legacy_id[identity.legacy_politician_id].add(identity.person_id)
        for key in identity.deterministic_keys:
            self._person_ids_by_key[key].add(identity.person_id)

    def resolve(self, packet: IdentityPacket) -> IdentityResolution:
        keys = identity_keys_from_packet(packet)
        if not keys:
            legacy_match = self._resolve_by_legacy_id(packet)
            if legacy_match:
                return legacy_match

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
                        "normalized_names": list(packet.normalized_names)
                        or [
                            name
                            for name in (
                                normalize_identity_name(value) for value in packet.names
                            )
                            if name
                        ],
                    },
                ),
            )

        matching_person_ids = self._person_ids_for_keys(keys)
        legacy_person_ids = self._person_ids_for_legacy_id(packet)

        if len(matching_person_ids) == 1:
            if len(legacy_person_ids) > 1:
                self._increment("identity_blocked_conflicts")
                return IdentityResolution(
                    action="blocked_conflict",
                    deterministic_keys=keys,
                    legacy_politician_id=packet.legacy_politician_id,
                    matching_person_ids=tuple(matching_person_ids),
                    legacy_person_ids=tuple(legacy_person_ids),
                    blocked_reason="legacy_politician_id_matches_multiple_people",
                )

            if len(legacy_person_ids) == 1 and legacy_person_ids != matching_person_ids:
                self._increment("identity_blocked_conflicts")
                return IdentityResolution(
                    action="blocked_conflict",
                    deterministic_keys=keys,
                    legacy_politician_id=packet.legacy_politician_id,
                    matching_person_ids=tuple(matching_person_ids),
                    legacy_person_ids=tuple(legacy_person_ids),
                    blocked_reason="deterministic_keys_conflict_with_legacy_mapping",
                )

            self._increment("identity_deterministic_matches")
            return IdentityResolution(
                action="matched_existing_person",
                deterministic_keys=keys,
                person_id=matching_person_ids[0],
                legacy_politician_id=packet.legacy_politician_id,
                matching_person_ids=tuple(matching_person_ids),
                legacy_person_ids=tuple(legacy_person_ids),
            )

        if len(matching_person_ids) > 1:
            self._increment("identity_blocked_conflicts")
            return IdentityResolution(
                action="blocked_conflict",
                deterministic_keys=keys,
                legacy_politician_id=packet.legacy_politician_id,
                matching_person_ids=tuple(matching_person_ids),
                legacy_person_ids=tuple(legacy_person_ids),
                blocked_reason="deterministic_keys_match_multiple_people",
            )

        if len(legacy_person_ids) == 1:
            return IdentityResolution(
                action="matched_existing_person",
                deterministic_keys=keys,
                person_id=legacy_person_ids[0],
                legacy_politician_id=packet.legacy_politician_id,
                matching_person_ids=tuple(matching_person_ids),
                legacy_person_ids=tuple(legacy_person_ids),
            )

        if len(legacy_person_ids) > 1:
            self._increment("identity_blocked_conflicts")
            return IdentityResolution(
                action="blocked_conflict",
                deterministic_keys=keys,
                legacy_politician_id=packet.legacy_politician_id,
                matching_person_ids=tuple(matching_person_ids),
                legacy_person_ids=tuple(legacy_person_ids),
                blocked_reason="legacy_politician_id_matches_multiple_people",
            )

        self._increment("identity_people_created")
        return IdentityResolution(
            action="create_person",
            deterministic_keys=keys,
            legacy_politician_id=packet.legacy_politician_id,
            matching_person_ids=tuple(matching_person_ids),
            legacy_person_ids=tuple(legacy_person_ids),
        )

    def _resolve_by_legacy_id(self, packet: IdentityPacket) -> IdentityResolution | None:
        matching_person_ids = self._person_ids_for_legacy_id(packet)
        if len(matching_person_ids) == 1:
            return IdentityResolution(
                action="matched_existing_person",
                legacy_politician_id=packet.legacy_politician_id,
                person_id=matching_person_ids[0],
                legacy_person_ids=tuple(matching_person_ids),
            )

        if len(matching_person_ids) > 1:
            self._increment("identity_blocked_conflicts")
            return IdentityResolution(
                action="blocked_conflict",
                legacy_politician_id=packet.legacy_politician_id,
                legacy_person_ids=tuple(matching_person_ids),
                blocked_reason="legacy_politician_id_matches_multiple_people",
            )

        return None

    def _person_ids_for_keys(self, keys: tuple[IdentityKey, ...]) -> list[str]:
        return sorted(
            {
                person_id
                for key in keys
                for person_id in self._person_ids_by_key.get(key, set())
            }
        )

    def _person_ids_for_legacy_id(self, packet: IdentityPacket) -> list[str]:
        if not packet.legacy_politician_id:
            return []
        return sorted(self._person_ids_by_legacy_id.get(packet.legacy_politician_id, set()))

    def _increment(self, key: str, amount: int = 1) -> None:
        if self.summary:
            self.summary.increment(key, amount)
