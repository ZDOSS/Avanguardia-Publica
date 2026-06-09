"""
Cross-source politician matching engine.

Seed flow:
1. Congress.gov is authoritative for federal legislators
2. VoteView provides crosswalk between bioguide ↔ icpsr
3. FEC candidates matched via FEC ↔ bioguide mapping
4. OpenSecrets CIDs via name + state/district as fallback
5. Unmatched entities land in admin resolution queue
"""

from dataclasses import dataclass


@dataclass
class EntityMatch:
    bioguide_id: str
    fec_ids: list[str]
    icpsr_id: str | None = None
    voteview_id: str | None = None
    opensecrets_id: str | None = None
    govtrack_id: str | None = None
    confidence: float = 1.0


class EntityResolver:
    """Match politicians across data source identifiers."""

    def build_crosswalk(self, voteview_data: list[dict]) -> list[EntityMatch]:
        """Build crosswalks from VoteView data (bioguide ↔ icpsr ↔ voteview)."""
        crosswalks: list[EntityMatch] = []
        for row in voteview_data:
            raw_icpsr = row.get("icpsr_id")
            raw_voteview = row.get("id")
            crosswalks.append(EntityMatch(
                bioguide_id=row.get("bioguide_id", ""),
                icpsr_id=str(raw_icpsr) if raw_icpsr is not None else None,
                voteview_id=str(raw_voteview) if raw_voteview is not None else None,
                fec_ids=[],
                confidence=1.0,
            ))
        return crosswalks

    def match_by_name_state(
        self,
        name: str,
        state: str,
        candidates: list[dict],
    ) -> str | None:
        """Fuzzy match a politician name + state to a candidate with an FEC ID."""
        name_lower = name.lower().strip()
        for c in candidates:
            c_name = c.get("name", "").lower().strip()
            c_state = c.get("state", "").upper()
            if c_state == state.upper() and name_lower == c_name:
                return c.get("fec_id")
        return None
