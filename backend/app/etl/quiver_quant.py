"""Quiver Quant congressional trading adapter.

Source: https://api.quiverquant.com/beta/
Auth:   QUIVER_QUANT_API_KEY env var (paid tier; required)

Quiver Quant aggregates publicly disclosed STOCK Act trades by U.S.
congressional members. The ``/beta/historical/congresstrading/{ticker}`` and
``/beta/live/congresstrading`` endpoints return rows of
``{Date, Ticker, Transaction, Amount, Senator, Representative, Party, ...}``.

Strategy:
- Pull the live "all members" feed once per sync.
- Each filing's ``Date+Ticker+Transaction+Representative`` tuple becomes the
  stable ``source_record_id`` (Quiver does not expose a public filing ID).
- politician_id is resolved by full name (Representative/Senator column) +
  chamber. We do best-effort matching; unmatched rows are stored without
  politician_id for later admin resolution.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.etl.base import BaseSourceAdapter


class QuiverQuantAdapter(BaseSourceAdapter):
    """Congressional stock-trade disclosures aggregated by Quiver Quant."""

    source_name = "quiver_quant"
    base_url = "https://api.quiverquant.com/beta"
    max_pages_default = 1  # single bulk pull

    async def fetch_records(self) -> list[dict[str, Any]]:
        if not settings.quiver_quant_api_key:
            return []
        headers = {"Authorization": f"Bearer {settings.quiver_quant_api_key}"}
        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(headers=headers) as client:
            for endpoint in ("live/congresstrading", "live/congresstrading_politicians"):
                try:
                    resp = await client.get(
                        f"{self.base_url}/{endpoint}",
                        timeout=60,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    continue
                data = resp.json()
                if isinstance(data, list):
                    records.extend(data)
                elif isinstance(data, dict):
                    for key in ("data", "results", "trades"):
                        if key in data and isinstance(data[key], list):
                            records.extend(data[key])
                            break
        return records

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map a Quiver row to FinancialDisclosure."""
        date_str = str(raw.get("Date") or raw.get("TradeDate") or "")[:10]
        ticker = raw.get("Ticker") or raw.get("Symbol") or ""
        tx = raw.get("Transaction") or raw.get("TransactionType") or ""
        rep = raw.get("Representative") or raw.get("Senator") or raw.get("Member") or ""
        amount = raw.get("Amount") or raw.get("TradeSize")
        amount_low, amount_high = _parse_amount_range(amount)
        return {
            "_model": "FinancialDisclosure",
            "filing_year": _parse_year(date_str),
            "filing_type": "STOCK Act PTR",
            "asset_name": f"{ticker} common stock" if ticker else None,
            "asset_type": "equity",
            "transaction_type": tx or None,
            "amount_range_low": amount_low,
            "amount_range_high": amount_high,
            "notification_date": _parse_iso_date(date_str),
            "source_url": raw.get("Source") or raw.get("source_url"),
            "ticker": ticker or None,
            "source_name": self.source_name,
            "source_record_id": f"quiver-{date_str}-{ticker}-{tx}-{rep}".replace(" ", "_"),
            "_filer_name": rep,
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import FinancialDisclosure, Politician

        model_name = record.pop("_model", None)
        filer_name = record.pop("_filer_name", None)

        if filer_name:
            parts = filer_name.split()
            last = parts[-1] if parts else ""
            first = parts[0] if len(parts) > 1 else ""
            politician = (
                db.query(Politician)
                .filter(
                    Politician.last_name.ilike(last),
                    Politician.first_name.ilike(first or "%"),
                )
                .first()
            )
            if politician:
                record["politician_id"] = politician.id

        existing = db.query(FinancialDisclosure).filter(
            FinancialDisclosure.source_name == record["source_name"],
            FinancialDisclosure.source_record_id == record["source_record_id"],
        ).first()
        if existing:
            for k, v in record.items():
                setattr(existing, k, v)
        else:
            db.add(FinancialDisclosure(**record))


def _parse_iso_date(value: Any):
    if not value:
        return None
    from datetime import datetime
    s = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").year
    except ValueError:
        return None


def _parse_amount_range(value: Any) -> tuple[float | None, float | None]:
    if value is None or value == "":
        return None, None
    s = str(value).replace("$", "").replace(",", "").strip()
    if "-" in s and s.count("-") == 1:
        parts = s.split("-")
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    try:
        f = float(s)
        return f, f
    except ValueError:
        return None, None
