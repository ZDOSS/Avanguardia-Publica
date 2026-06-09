"""California Cal-Access bulk CSV importer.

Cal-Access (https://cal-access.sos.ca.gov/) is the California Secretary
of State's campaign finance disclosure system. The bulk CSV exports
cover every state-legislator campaign committee and the contributions
to / expenditures by those committees.

Source: https://cal-access.sos.ca.gov/downloads/
Two tables are relevant for Phase 5:

  - ``Cn_Lobbyist_Cd.csv``           — lobbyists registered with the state
  - ``Cover_Page_Cd.csv``             — campaign cover-page records (committee + candidate)
  - ``Rcpt_Cd.csv``                   — contributions received by committees

For the initial Phase 5 deliverable the adapter focuses on the
candidate/cover-page roll-up: it reads ``Cover_Page_Cd.csv`` (one row
per filing, each filing is tied to a filer_id and a candidate name) and
upserts one Politician row per unique candidate.

Committee-level campaign finance (Rcpt_Cd) is a follow-up; the schema
is the same as the federal Contribution table, but the source-of-record
flag is ``ca_calaccess`` rather than ``fec_api``.
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


class CACalAccessAdapter(BaseSourceAdapter):
    """Bulk importer for California Cal-Access cover-page records."""

    source_name = "ca_calaccess"
    max_pages_default = 1  # bulk file processing, not paginated
    jurisdiction_level = "state"
    country_code = "US"

    async def fetch_records(self, file_path: str | None = None) -> list[dict[str, Any]]:
        """Read ``Cover_Page_Cd.csv`` (or the caller-supplied path)."""
        base = Path(file_path or settings.ca_calaccess_bulk_path)
        if not base:
            return []

        # The Cal-Access export unzips to a flat directory of CSVs. If
        # the user points us at the directory, pick the cover-page file
        # by its canonical name; if they hand us a single file, use it.
        if base.is_dir():
            candidates = sorted(base.glob("Cover_Page*.csv"))
            if not candidates:
                return []
            paths = candidates
        else:
            paths = [base]

        records: list[dict[str, Any]] = []
        for path in paths:
            with open(path, encoding="latin-1", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    normalized = self._row_to_dict(row)
                    if normalized is not None:
                        records.append(normalized)
        return records

    def _row_to_dict(self, row: dict[str, str]) -> dict[str, Any] | None:
        """Pull the candidate/committee fields out of a cover-page row."""
        # Cal-Access uses ALL-CAPS column names; tolerate either case.
        lookup = {k.lower(): v for k, v in row.items()}

        first = _safe_strip_or_none(lookup.get("cand_first_name"))
        last = _safe_strip_or_none(lookup.get("cand_last_name"))
        if not first and not last:
            # Pure committee filing (PAC, ballot measure); not a person.
            return None

        full_name_parts = [
            p for p in (_safe_strip_or_none(lookup.get("cand_title")),
                        first, _safe_strip_or_none(lookup.get("cand_middle_name")), last,
                        _safe_strip_or_none(lookup.get("cand_name_suffix"))) if p
        ]
        full_name = " ".join(full_name_parts).strip()
        if not full_name:
            full_name = f"{first or ''} {last or ''}".strip()

        party = _safe_strip_or_none(lookup.get("cand_party"))
        committee_id = _safe_strip_or_none(lookup.get("filer_id"))
        office = _safe_strip_or_none(lookup.get("cand_office")) or ""
        office_lower = office.lower()
        if "state senate" in office_lower or office_lower == "senate":
            chamber = "state_senate"
        elif "state assembly" in office_lower or "assembly" in office_lower or office_lower == "house":
            chamber = "state_house"
        elif "governor" in office_lower:
            chamber = "governor"
        else:
            chamber = "state_house"  # default for CA legislative offices

        # Cal-Access doesn't include a district field on the cover page
        # itself, so we leave it as None. The Contributions page in a
        # future adapter will resolve district from FilerID join.

        # Stable per-candidate key: (last, first, party, chamber). The
        # same person running in two different cycles will collapse,
        # which is desirable for the candidate catalog.
        key_seed = f"{last}|{first}|{party}|{chamber}".encode()
        source_record_id = f"ca-calaccess-{hashlib.sha256(key_seed).hexdigest()[:16]}"

        return {
            "first_name": first or "",
            "middle_name": _safe_strip_or_none(lookup.get("cand_middle_name")),
            "last_name": last or "",
            "full_name": full_name,
            "party_history": [{"party": party, "start_date": None, "end_date": None}] if party else None,
            "country_code": self.country_code,
            "jurisdiction_level": self.jurisdiction_level,
            "state": "CA",
            "district": None,
            "chamber": chamber,
            "in_office": False,  # Cal-Access exports historical filings; refresh in_office from a separate feed
            "source_name": self.source_name,
            "source_record_id": source_record_id,
            "_model_marker": "Politician",
            "_filer_id": committee_id,
        }

    def normalize(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Drop the model marker so the base upsert can route on type alone."""
        if raw.get("_model_marker") != "Politician":
            return {}
        return {k: v for k, v in raw.items() if not k.startswith("_")}

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
