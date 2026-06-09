"""House Clerk financial disclosure (stock trade) adapter.

Source: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip
Auth:   none (public bulk download)

The House Clerk publishes annual ZIP archives of financial disclosure PDFs.
The STOCK Act (2012) requires Members of the House to file periodic
transaction reports (PTRs) within 45 days of a trade. The bulk ZIPs include
XML index files (``{year}FD.xml``) that list filer name, transaction date,
ticker, asset name, and transaction type.

Strategy:
- Download the most recent year's ZIP.
- Parse the XML index, not the PDFs, to avoid binary parsing.
- Map rows to FinancialDisclosure; politician_id is resolved by name + chamber
  to a House member.
"""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from typing import Any

import httpx

from app.etl.base import BaseSourceAdapter


class HouseClerkAdapter(BaseSourceAdapter):
    """House Clerk STOCK Act transaction disclosures."""

    source_name = "house_clerk"
    base_url = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs"
    max_pages_default = 1  # single bulk download

    async def fetch_records(self, year: int | None = None) -> list[dict[str, Any]]:
        target_year = year or datetime.utcnow().year
        url = f"{self.base_url}/{target_year}FD.zip"
        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, timeout=120, follow_redirects=True)
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                return records
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_name = f"{target_year}FD.xml"
                if xml_name not in zf.namelist():
                    return records
                with zf.open(xml_name) as xml_file:
                    tree = ET.parse(xml_file)
            for member in tree.getroot().iter("Member"):
                records.append(self._member_to_raw(member, target_year))
        except (zipfile.BadZipFile, ET.ParseError):
            return records
        return records

    def _member_to_raw(self, member: ET.Element, year: int) -> dict[str, Any]:
        """Convert a <Member> element to a flat record list (one per asset)."""
        first = _elem_text(member, "FirstName") or ""
        last = _elem_text(member, "LastName") or ""
        prefix = _elem_text(member, "Prefix") or ""
        filing_type = _elem_text(member, "FilingType") or ""
        records: list[dict[str, Any]] = []
        for asset in member.iter("Asset"):
            asset_name = _elem_text(asset, "AssetName") or _elem_text(asset, "Description")
            ticker = _elem_text(asset, "Ticker")
            transaction = _elem_text(asset, "TransactionType") or _elem_text(asset, "Type")
            notification_date = _parse_iso_date(_elem_text(asset, "NotificationDate"))
            amount_low, amount_high = _parse_amount_range(
                _elem_text(asset, "AmountLow") or _elem_text(asset, "AmountRangeLow"),
                _elem_text(asset, "AmountHigh") or _elem_text(asset, "AmountRangeHigh"),
            )
            doc_id = _elem_text(asset, "DocID") or _elem_text(member, "DocID")
            records.append({
                "_filer_prefix": prefix,
                "_filer_first": first,
                "_filer_last": last,
                "filing_year": year,
                "filing_type": filing_type,
                "asset_name": asset_name,
                "asset_type": _elem_text(asset, "AssetType"),
                "transaction_type": transaction,
                "amount_range_low": amount_low,
                "amount_range_high": amount_high,
                "notification_date": notification_date,
                "source_url": doc_id and f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}/{doc_id}.pdf",
                "ticker": ticker,
            })
        return {"_member_records": records}

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map a House Clerk disclosure row to FinancialDisclosure."""
        if "_member_records" in raw:
            return {"_type": "member_group", "records": raw["_member_records"]}
        doc_id = (raw.get("source_url") or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return {
            "_model": "FinancialDisclosure",
            "filing_year": raw.get("filing_year"),
            "filing_type": raw.get("filing_type"),
            "asset_name": raw.get("asset_name"),
            "asset_type": raw.get("asset_type"),
            "transaction_type": raw.get("transaction_type"),
            "amount_range_low": raw.get("amount_range_low"),
            "amount_range_high": raw.get("amount_range_high"),
            "notification_date": raw.get("notification_date"),
            "source_url": raw.get("source_url"),
            "ticker": raw.get("ticker"),
            "source_name": self.source_name,
            "source_record_id": doc_id or f"house-clerk-{raw.get('filing_year')}-{raw.get('ticker')}-{raw.get('notification_date')}",
            "_filer_first": raw.get("_filer_first"),
            "_filer_last": raw.get("_filer_last"),
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import FinancialDisclosure, Politician

        if record.get("_type") == "member_group":
            for inner in record.pop("records", []):
                await self._upsert(inner, db=db)
            return

        model_name = record.pop("_model", None)
        filer_first = record.pop("_filer_first", None)
        filer_last = record.pop("_filer_last", None)

        if filer_last:
            politician = (
                db.query(Politician)
                .filter(
                    Politician.last_name.ilike(filer_last),
                    Politician.first_name.ilike(filer_first or "%"),
                    Politician.chamber == "house",
                )
                .first()
            )
            if politician:
                record["politician_id"] = politician.id

        if "politician_id" not in record:
            return  # skip unmatched filers

        existing = db.query(FinancialDisclosure).filter(
            FinancialDisclosure.source_name == record["source_name"],
            FinancialDisclosure.source_record_id == record["source_record_id"],
        ).first()
        if existing:
            for k, v in record.items():
                setattr(existing, k, v)
        else:
            db.add(FinancialDisclosure(**record))


def _elem_text(parent: ET.Element, tag: str) -> str | None:
    el = parent.find(tag)
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _parse_iso_date(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount_range(low: str | None, high: str | None) -> tuple[float | None, float | None]:
    def _to_float(v: str | None) -> float | None:
        if not v:
            return None
        cleaned = re.sub(r"[^\d.\-]", "", v)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return _to_float(low), _to_float(high)
