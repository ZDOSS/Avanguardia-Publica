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
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


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


def packet_from_legacy_politician(row: dict) -> IdentityPacket:
    external_ids = dict(row.get("external_ids") or {})
    if row.get("bioguide_id"):
        external_ids["bioguide"] = row["bioguide_id"]

    names = [row.get("full_name")]
    names.extend(row.get("aliases") or [])

    return IdentityPacket(
        source_system_key="avanguardia-legacy-profile",
        source_record_key=row.get("id"),
        legacy_politician_id=row.get("id"),
        names=tuple(name for name in names if name),
        external_ids=external_ids,
        role_facts={
            "current_office": row.get("current_office"),
            "party": row.get("party"),
            "state": row.get("state"),
            "district": row.get("district"),
            "government_level": row.get("government_level"),
            "government_branch": row.get("government_branch"),
            "office_type": row.get("office_type"),
            "jurisdiction": row.get("jurisdiction"),
        },
    )
