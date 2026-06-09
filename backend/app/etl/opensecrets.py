"""OpenSecrets bulk data importer for campaign finance enrichment.

OpenSecrets provides bulk CSV files covering:
- Campaign contributions by individual donors
- PAC contributions to candidates
- Industry/sector classifications
- Organization summaries (PACs, committees, corporations)

Source: https://www.opensecrets.org/bulk-data
Requires account + approval (free for edu/nonprofit).

The adapter reads from a local directory specified by OPENSECRETS_BULK_PATH.
Expected files (industry-standard OpenSecrets format):
- indivs{year}.txt  — individual contributions
- pacs{year}.txt    — PAC contributions
- cmtes{year}.txt  — committee master file
"""

import csv
import hashlib
import os
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.etl.base import BaseSourceAdapter


def _safe_strip(value, default: str = ""):
    """Safely strip a value that may be None, returning default if None/empty."""
    if value is None:
        return default
    stripped = str(value).strip()
    return stripped if stripped else default


def _safe_strip_or_none(value):
    """Safely strip a value that may be None, returning None if empty/None."""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


class OpenSecretsAdapter(BaseSourceAdapter):
    """Bulk importer for OpenSecrets campaign finance data."""

    source_name = "opensecrets_bulk"
    max_pages_default = 1  # bulk file processing, not paginated

    # OpenSecrets bulk data uses a fixed-width / pipe-delimited format
    # Individual contributions: indivs{year}.txt
    # PAC contributions: pacs{year}.txt
    # Committee master: cmtes{year}.txt

    async def fetch_records(self, years: list[int] | None = None) -> list[dict[str, Any]]:
        """Read OpenSecrets bulk files from the configured path."""
        base_path = settings.opensecrets_bulk_path
        if not base_path:
            return []

        base = Path(base_path)
        if not base.exists():
            return []

        # Default to current + previous cycle
        target_years = years or [2024, 2022]
        records = []

        for year in target_years:
            # Individual contributions
            indivs_file = base / f"indivs{year}.txt"
            if indivs_file.exists():
                with open(indivs_file, "r", encoding="latin-1") as f:
                    reader = csv.DictReader(f, delimiter="|", fieldnames=[
                        "cycle", "fec_trans_id", "contrib_id", "contrib",
                        "recip_id", "org_name", "ult_org", "real_code",
                        "date", "amount", "street", "city", "state",
                        "zip", "recip_code", "type", "cmte_id", "other_id",
                        "gender", "microfilm", "occupation", "employer",
                        "source"
                    ])
                    for row in reader:
                        records.append({
                            "_type": "contribution",
                            "cycle": row.get("cycle"),
                            "donor_name": _safe_strip(row.get("contrib")),
                            "recipient_id": _safe_strip(row.get("recip_id")),
                            "committee_id": _safe_strip_or_none(row.get("cmte_id")),
                            "organization_name": _safe_strip_or_none(row.get("org_name")),
                            "ultimate_org": _safe_strip_or_none(row.get("ult_org")),
                            "industry_code": _safe_strip_or_none(row.get("real_code")),
                            "amount": _safe_strip(row.get("amount"), default="0"),
                            "date": _safe_strip_or_none(row.get("date")),
                            "city": _safe_strip_or_none(row.get("city")),
                            "state": _safe_strip_or_none(row.get("state")),
                            "zip": _safe_strip_or_none(row.get("zip")),
                            "occupation": _safe_strip_or_none(row.get("occupation")),
                            "employer": _safe_strip_or_none(row.get("employer")),
                            "gender": _safe_strip_or_none(row.get("gender")),
                        })

            # PAC contributions
            pacs_file = base / f"pacs{year}.txt"
            if pacs_file.exists():
                with open(pacs_file, "r", encoding="latin-1") as f:
                    reader = csv.DictReader(f, delimiter="|", fieldnames=[
                        "cycle", "fec_rec_no", "pac_id", "cid", "amount",
                        "date", "real_code", "type", "di", "feccandid"
                    ])
                    for row in reader:
                        records.append({
                            "_type": "contribution",
                            "cycle": row.get("cycle"),
                            "donor_name": _safe_strip(row.get("pac_id")),  # TODO: resolve to cmte_name via committee master lookup
                            "donor_type": "pac",
                            "recipient_id": _safe_strip(row.get("cid")),
                            "committee_id": _safe_strip_or_none(row.get("pac_id")),
                            "industry_code": _safe_strip_or_none(row.get("real_code")),
                            "amount": _safe_strip(row.get("amount"), default="0"),
                            "date": _safe_strip_or_none(row.get("date")),
                        })

            # Committee master (for organization metadata)
            cmtes_file = base / f"cmtes{year}.txt"
            if cmtes_file.exists():
                with open(cmtes_file, "r", encoding="latin-1") as f:
                    reader = csv.DictReader(f, delimiter="|", fieldnames=[
                        "cmte_id", "cmte_name", "treasurer", "street1", "street2",
                        "city", "state", "zip", "cmte_designation", "cmte_type",
                        "cmte_pty_affiliation", "cmte_filing_freq", "org_type",
                        "connected_org_name", "candidate_id"
                    ])
                    for row in reader:
                        records.append({
                            "_type": "organization",
                            "opensecrets_id": _safe_strip(row.get("cmte_id")),
                            "name": _safe_strip(row.get("cmte_name")),
                            "type": self._map_cmte_type(_safe_strip(row.get("cmte_type"))),
                            "party_affiliation": _safe_strip_or_none(row.get("cmte_pty_affiliation")),
                            "connected_org": _safe_strip_or_none(row.get("connected_org_name")),
                        })

        return records

    def _map_cmte_type(self, raw: str) -> str:
        """Map OpenSecrets committee type to our Organization.type enum."""
        mapping = {
            "H": "house",
            "S": "senate",
            "P": "presidential",
            "Q": "pac",
            "N": "pac",
            "O": "super_pac",
            "U": "super_pac",
            "V": "hybrid",
            "W": "hybrid",
            "C": "corporation",
            "L": "labor",
            "M": "membership",
            "T": "trade",
            "Y": "corporation",
            "Z": "national_party",
        }
        return mapping.get(raw.upper(), "committee")

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map OpenSecrets raw record to unified model."""
        record_type = raw.get("_type")
        if record_type == "contribution":
            return self._normalize_contribution(raw)
        elif record_type == "organization":
            return self._normalize_organization(raw)
        return {}

    def _normalize_contribution(self, raw: dict) -> dict[str, Any]:
        amount_raw = raw.get("amount", "0")
        amount_str = str(amount_raw).strip() if amount_raw is not None else "0"
        try:
            amount = float(amount_str)
        except ValueError:
            amount = 0.0

        # Use OpenSecrets transaction ID + cycle as source_record_id if available
        # Fallback: sha256 hash of donor+recipient+date+amount for stable dedup
        cycle = raw.get("cycle", "")
        donor = raw.get("donor_name", "")
        recipient = raw.get("recipient_id", "")
        date = raw.get("date", "")
        _key = f"{cycle}|{donor}|{recipient}|{date}|{amount_str}"
        source_record_id = f"opensecrets-{cycle}-{hashlib.sha256(_key.encode()).hexdigest()[:16]}"

        return {
            "_model": "Contribution",
            "donor_name": raw.get("donor_name", ""),
            "donor_type": raw.get("donor_type", "individual"),
            "recipient_name": "",  # resolved to politician.last_name in _upsert when politician_id is set
            "committee_id": raw.get("committee_id"),
            "amount": amount,
            "date": raw.get("date"),
            "election_cycle": int(cycle) if cycle and cycle.isdigit() else None,
            "location": f"{raw.get('city', '')}, {raw.get('state', '')}" if raw.get("city") or raw.get("state") else None,
            "employer": raw.get("employer"),
            "occupation": raw.get("occupation"),
            "source_name": self.source_name,
            "source_record_id": source_record_id,
            "_opensecrets_recipient_id": raw.get("recipient_id"),
            "_industry_code": raw.get("industry_code"),
        }

    def _normalize_organization(self, raw: dict) -> dict[str, Any]:
        opensecrets_id = raw.get("opensecrets_id", "")
        return {
            "_model": "Organization",
            "name": raw["name"],
            "type": raw["type"],
            "opensecrets_id": opensecrets_id or None,
            "source_name": self.source_name,
            "source_record_id": opensecrets_id or f"opensecrets-org-{raw['name']}",
            "metadata_": {
                "party_affiliation": raw.get("party_affiliation"),
                "connected_org": raw.get("connected_org"),
            },
        }

    async def _upsert(self, record: dict, db=None) -> None:
        """Insert or update a normalized OpenSecrets record."""
        from app.models import Politician, Contribution, Organization

        model_name = record.pop("_model")

        if model_name == "Contribution":
            # Resolve politician by OpenSecrets CID (candidate ID)
            recipient_id = record.pop("_opensecrets_recipient_id", None)
            industry_code = record.pop("_industry_code", None)

            if recipient_id:
                politician = db.query(Politician).filter(
                    Politician.opensecrets_id == recipient_id
                ).first()
                if politician:
                    record["politician_id"] = politician.id
                    record["recipient_name"] = politician.last_name

            # Upsert by source_name + source_record_id
            existing = db.query(Contribution).filter(
                Contribution.source_name == record["source_name"],
                Contribution.source_record_id == record["source_record_id"],
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                db.add(Contribution(**record))

        elif model_name == "Organization":
            # Upsert by source_name + source_record_id
            if not record.get("source_name") or not record.get("source_record_id"):
                return

            existing = db.query(Organization).filter(
                Organization.source_name == record["source_name"],
                Organization.source_record_id == record["source_record_id"],
            ).first()
            if existing:
                for k, v in record.items():
                    setattr(existing, k, v)
            else:
                db.add(Organization(**record))
