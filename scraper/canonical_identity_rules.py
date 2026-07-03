from collections import defaultdict, deque
from itertools import combinations
import re


TRUSTED_EXTERNAL_ID_FIELDS = {
    "openstates": "openstates_person_id",
    "govtrack": "govtrack_person_id",
    "wikidata": "wikidata_qid",
    "fec": "fec_candidate_id",
    "fjc": "fjc_judge_id",
}


def normalize_identity_name(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    return normalized or None


def _as_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    return [str(item).strip() for item in values if str(item).strip()]


def deterministic_identity_keys(row: dict) -> tuple[tuple[str, str, str], ...]:
    keys: list[tuple[str, str, str]] = []
    bioguide_id = (row.get("bioguide_id") or "").strip()
    if bioguide_id:
        keys.append(("bioguide", "bioguide_id", bioguide_id))

    external_ids = row.get("external_ids") or {}
    for scheme, key_type in TRUSTED_EXTERNAL_ID_FIELDS.items():
        for value in _as_values(external_ids.get(scheme)):
            keys.append((scheme, key_type, value))

    return tuple(keys)


def group_profiles_by_deterministic_identity(rows: list[dict]) -> dict[str, str]:
    adjacency: dict[str, set[str]] = {row["id"]: set() for row in rows}
    rows_by_key: dict[tuple[str, str, str], list[str]] = defaultdict(list)

    for row in rows:
        for key in deterministic_identity_keys(row):
            rows_by_key[key].append(row["id"])

    for ids in rows_by_key.values():
        for left, right in combinations(ids, 2):
            adjacency[left].add(right)
            adjacency[right].add(left)

    group_by_id: dict[str, str] = {}
    for row_id in sorted(adjacency):
        if row_id in group_by_id:
            continue
        queue = deque([row_id])
        component = []
        while queue:
            current = queue.popleft()
            if current in group_by_id:
                continue
            component.append(current)
            group_by_id[current] = row_id
            queue.extend(sorted(adjacency[current] - set(group_by_id)))

        group_id = min(component)
        for component_id in component:
            group_by_id[component_id] = group_id

    return group_by_id


def same_name_review_candidates(rows: list[dict], group_by_id: dict[str, str]) -> list[dict]:
    candidates = []
    rows_by_name: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        normalized = normalize_identity_name(row.get("full_name"))
        if normalized:
            rows_by_name[normalized].append(row)

    for normalized_name, named_rows in rows_by_name.items():
        for left, right in combinations(sorted(named_rows, key=lambda item: item["id"]), 2):
            if group_by_id[left["id"]] == group_by_id[right["id"]]:
                continue
            left_has_keys = bool(deterministic_identity_keys(left))
            right_has_keys = bool(deterministic_identity_keys(right))
            candidates.append(
                {
                    "candidate_type": (
                        "same_name_conflicting_deterministic_ids"
                        if left_has_keys and right_has_keys
                        else "same_name_review"
                    ),
                    "source_legacy_politician_id": left["id"],
                    "candidate_legacy_politician_id": right["id"],
                    "normalized_name": normalized_name,
                }
            )

    return candidates
