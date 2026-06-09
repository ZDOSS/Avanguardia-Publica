"""Elections Canada bulk CSV importer.

Elections Canada publishes the official election results for every
federal general election as open data on open.canada.ca. The dataset is
broken up by election year; each CSV contains one row per candidate
(name, party, riding, votes, result).

Source: https://open.canada.ca/data/en/dataset?keywords=candidates
Expected file format (Elections Canada open data CSV, headers vary by
election year but follow the same conceptual schema):

  Election_Number, Election_Date, Election_Type, Province_Name,
  Province_Code, Riding_Name, Riding_Number, Candidate_Number,
  Candidate_First_Name, Candidate_Middle_Name, Candidate_Last_Name,
  Candidate_Party_Name, Candidate_Party_Abbreviation,
  Candidate_Votes, Candidate_Vote_Percent, Candidate_Result,
  Majority_Mark, Number_Of_Valid_Ballots, Number_Of_Rejected_Ballots,
  Number_Of_Total_Ballots, Elected_Candidate_Indicator

The adapter reads from a local directory specified by
``CANADA_ELECTIONS_BULK_PATH`` (same pattern as the OpenSecrets bulk
adapter) and upserts one Politician row per unique candidate plus one
Contribution-style summary row per candidate per election.

For Phase 5, the focus is the politician catalog: the source gives us
name, party, riding (mapped to ``state``), chamber ('house' — Canada's
House of Commons), and election results. We do not yet ingest Canadian
campaign finance data (separate Elections Canada dataset) — that's a
follow-up once the politician catalog is in.
"""

import csv
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.etl.base import BaseSourceAdapter


def _safe_strip_or_none(value):
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def _safe_strip(value, default: str = ""):
    if value is None:
        return default
    stripped = str(value).strip()
    return stripped if stripped else default


def _parse_canada_election_date(value) -> datetime | None:
    """Parse Elections Canada ``YYYY-MM-DD`` (or close variants) to a date."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# Mapping from Elections Canada province codes to our 2-letter ``state``
# column. Canadian provinces already use 2-letter postal codes so this
# is a no-op in most cases; territories use 2-letter codes too.
_PROVINCE_PASS_THROUGH = set(
    ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"]
)


def _normalize_province(raw: str | None) -> str:
    if not raw:
        return ""
    code = str(raw).strip().upper()
    return code if code in _PROVINCE_PASS_THROUGH else ""


class CanadaElectionsAdapter(BaseSourceAdapter):
    """Bulk importer for Elections Canada candidate results."""

    source_name = "canada_elections"
    max_pages_default = 1  # bulk file processing, not paginated

    async def fetch_records(self, file_path: str | None = None) -> list[dict[str, Any]]:
        """Read one or more Elections Canada CSVs and return raw rows.

        ``file_path`` overrides ``CANADA_ELECTIONS_BULK_PATH`` for ad-hoc
        ingests. If the directory is unset, the adapter returns no
        records (same fallback as the OpenSecrets bulk adapter).
        """
        base = Path(file_path or settings.canada_elections_bulk_path)
        if not base:
            return []
        if base.is_file():
            candidates = [base]
        elif base.is_dir():
            candidates = sorted(base.glob("*.csv"))
        else:
            return []

        records: list[dict[str, Any]] = []
        for path in candidates:
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(self._row_to_dict(row, source_file=path.name))
        return records

    def _row_to_dict(self, row: dict[str, str], source_file: str) -> dict[str, Any]:
        first = _safe_strip_or_none(row.get("Candidate_First_Name"))
        middle = _safe_strip_or_none(row.get("Candidate_Middle_Name"))
        last = _safe_strip_or_none(row.get("Candidate_Last_Name"))
        full = " ".join(p for p in (first, middle, last) if p)
        party = _safe_strip_or_none(row.get("Candidate_Party_Abbreviation")) or _safe_strip_or_none(
            row.get("Candidate_Party_Name")
        )
        province = _normalize_province(row.get("Province_Code") or row.get("Province_Name"))
        riding = _safe_strip_or_none(row.get("Riding_Name"))
        election_date = _parse_canada_election_date(row.get("Election_Date"))
        result_raw = _safe_strip_or_none(row.get("Candidate_Result"))
        # Stable per-candidate key: (last, first, province, riding).
        # The combination of name + riding is unique within an election,
        # and we don't yet cross-resolve candidates across multiple
        # elections, so this is good enough for the initial catalog.
        key_seed = f"{last}|{first}|{province}|{riding}".encode()
        source_record_id = f"canada-{hashlib.sha256(key_seed).hexdigest()[:16]}"
        return {
            "_type": "politician",
            "first_name": first or "",
            "middle_name": middle,
            "last_name": last or "",
            "full_name": full,
            "party_abbreviation": party,
            "country_code": "CA",
            "jurisdiction_level": "federal",
            "state": province,
            "chamber": "house",  # House of Commons
            "district": riding,
            "in_office": (result_raw or "").lower() in {"elected", "winner"},
            "election_date": election_date,
            "election_result": result_raw,
            "source_file": source_file,
            "source_record_id": source_record_id,
        }

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Map raw Canada row to the unified politician schema.

        Wraps the row produced by ``_row_to_dict`` so the base
        ``run_sync`` loop gets a stable contract. ``_type`` is dropped
        before insert.
        """
        if raw.get("_type") != "politician":
            return {}
        return {
            "first_name": raw.get("first_name", ""),
            "middle_name": raw.get("middle_name"),
            "last_name": raw.get("last_name", ""),
            "full_name": raw.get("full_name", ""),
            "party_history": [
                {
                    "party": raw.get("party_abbreviation"),
                    "start_date": raw.get("election_date").isoformat() if raw.get("election_date") else None,
                    "end_date": None,
                }
            ]
            if raw.get("party_abbreviation")
            else None,
            "country_code": "CA",
            "jurisdiction_level": "federal",
            "state": raw.get("state", ""),
            "district": raw.get("district"),
            "chamber": "house",
            "in_office": raw.get("in_office", False),
            "source_name": self.source_name,
            "source_record_id": raw.get("source_record_id", ""),
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import Politician

        if not record.get("source_record_id"):
            return
        existing = (
            db.query(Politician)
            .filter(
                Politician.source_name == self.source_name,
                Politician.source_record_id == record["source_record_id"],
            )
            .first()
        )
        if existing:
            for k, v in record.items():
                setattr(existing, k, v)
            existing.last_data_refresh = datetime.now(UTC)
        else:
            db.add(Politician(**record))
