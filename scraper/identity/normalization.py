from __future__ import annotations

import re
from typing import Any

from .types import IdentityKey, IdentityPacket


TRUSTED_EXTERNAL_ID_TYPES = {
    "bioguide": "bioguide_id",
    "openstates": "openstates_person_id",
    "govtrack": "govtrack_person_id",
    "wikidata": "wikidata_qid",
    "fec": "fec_candidate_id",
    "fjc": "fjc_judge_id",
}


def normalize_identity_name(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    return normalized or None


def _as_values(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _source_names(row: dict) -> tuple[str, ...]:
    values = [row.get("full_name"), *(row.get("aliases") or [])]
    names = [str(value) for value in values if value is not None and str(value).strip()]
    return tuple(dict.fromkeys(names))


def _normalized_names(names: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [normalize_identity_name(name) for name in names]
    return tuple(dict.fromkeys(name for name in normalized if name))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def identity_keys_from_packet(packet: IdentityPacket) -> tuple[IdentityKey, ...]:
    keys: list[IdentityKey] = []
    for source_system_key, external_id_type in TRUSTED_EXTERNAL_ID_TYPES.items():
        for external_id in _as_values(packet.external_ids.get(source_system_key)):
            keys.append(
                IdentityKey(
                    source_system_key=source_system_key,
                    external_id_type=external_id_type,
                    external_id=external_id,
                )
            )
    return tuple(sorted(dict.fromkeys(keys)))


def trusted_external_keys(row: dict) -> tuple[IdentityKey, ...]:
    return identity_keys_from_packet(packet_from_source_profile(row))


def packet_from_source_profile(
    row: dict,
    *,
    legacy_politician_id: str | None = None,
) -> IdentityPacket:
    """Convert an extractor profile fact into the normalized Phase 3 packet.

    The packet deliberately carries both raw display names and normalized names.
    It also keeps source provenance, role/spoke facts, and review metadata together
    so the resolver, review queue, and transactional writer use the same evidence.
    """
    external_ids = _mapping(row.get("external_ids"))
    if row.get("bioguide_id"):
        external_ids["bioguide"] = row["bioguide_id"]

    names = _source_names(row)
    role_facts = {
        key: row.get(key)
        for key in (
            "current_office",
            "party",
            "state",
            "district",
            "government_level",
            "government_branch",
            "office_type",
            "jurisdiction",
            "source_term_key",
            "role_type",
            "organization_name",
            "term_start",
            "term_end",
            "term_status",
        )
    }
    spoke_facts = _mapping(row.get("spoke_facts"))
    if row.get("contact"):
        spoke_facts.setdefault("contact", row["contact"])

    return IdentityPacket(
        source_system_key=str(row.get("source_system_key") or "").strip(),
        source_record_key=(
            str(row["source_record_key"]).strip()
            if row.get("source_record_key") is not None
            else None
        ),
        legacy_politician_id=legacy_politician_id,
        source_url=row.get("source_url"),
        raw_payload_ref=row.get("raw_payload_ref"),
        source_catalog_slug=row.get("source_catalog_slug"),
        source_endpoint_slug=row.get("source_endpoint_slug"),
        payload_hash=row.get("payload_hash"),
        verified_lane=row.get("verified_lane"),
        source_updated_at=row.get("source_updated_at"),
        names=names,
        normalized_names=_normalized_names(names),
        external_ids=external_ids,
        role_facts=role_facts,
        spoke_facts=spoke_facts,
        confidence=row.get("confidence"),
        review_metadata=_mapping(row.get("review_metadata")),
    )


def packet_from_legacy_politician(row: dict) -> IdentityPacket:
    legacy_row = {
        **row,
        "source_system_key": "avanguardia-legacy-profile",
        "source_record_key": row.get("id"),
    }
    return packet_from_source_profile(
        legacy_row,
        legacy_politician_id=row.get("id"),
    )
