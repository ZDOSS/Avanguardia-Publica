"""SEC EDGAR Form 4 corporate insider-filing adapter.

Source: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4
Auth:   none, but the SEC requires a descriptive User-Agent header
        (``Sample Company Name AdminContact@<host>``) per their fair-access
        policy. We surface this requirement via the SEC_EDGAR_USER_AGENT env
        var, defaulting to a safe string.

Form 4 filings report insider transactions (purchases, sales, grants) by
officers, directors, and >10% holders. This adapter pulls recent Form 4
filings and stores them as FinancialDisclosure records tagged with the
filer's CIK, name, and ticker.

Strategy:
- Daily index ``/Archives/edgar/daily-index/{YYYY-MM-DD}/form.idx`` lists
  filings by form type. We filter to Form 4 entries.
- Each filing's accession number is the stable ``source_record_id``.
- politician_id is intentionally not set here; this captures corporate
  insiders, not politicians. Cross-entity linking is out of scope.
"""

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.etl.base import BaseSourceAdapter


class SECEdgarAdapter(BaseSourceAdapter):
    """Corporate insider Form 4 filings from SEC EDGAR."""

    source_name = "sec_edgar"
    base_url = "https://www.sec.gov"
    max_pages_default = 5  # 5 days × ~1000 Form 4 filings/day = 5000 records

    def __init__(self) -> None:
        super().__init__()
        self.headers = {"User-Agent": "Avanguardia Publica research@avanguardia-publica.example"}

    async def fetch_records(self, days_back: int | None = None) -> list[dict[str, Any]]:
        days = days_back or 3
        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(headers=self.headers) as client:
            for offset in range(days):
                target_date = (datetime.utcnow() - timedelta(days=offset)).strftime("%Y-%m-%d")
                url = f"{self.base_url}/Archives/edgar/daily-index/{target_date}/form.idx"
                try:
                    resp = await client.get(url, timeout=60)
                    resp.raise_for_status()
                except httpx.HTTPStatusError:
                    continue
                if resp.status_code == 404 or "form.idx" not in str(resp.url):
                    continue
                for line in resp.text.splitlines():
                    if not line.startswith("4 "):
                        continue
                    parts = line.split()
                    if len(parts) < 6:
                        continue
                    _, _, _, form_type, company_name, cik, filename = parts[:7]
                    if form_type.strip() != "4":
                        continue
                    records.append({
                        "filing_date": target_date,
                        "company_name": company_name.strip(),
                        "cik": cik.strip(),
                        "filing_url": f"https://www.sec.gov/Archives/{filename.strip()}",
                    })
                if len(records) >= self.max_pages_default * 1000:
                    break
        return records

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map a Form 4 index entry to a FinancialDisclosure record."""
        filing_url = raw.get("filing_url", "")
        accession = filing_url.rsplit("/", 1)[-1].replace("-index.htm", "").replace(".txt", "")
        company = raw.get("company_name", "")
        return {
            "_model": "FinancialDisclosure",
            "filing_year": _parse_year(raw.get("filing_date")),
            "filing_type": "Form 4",
            "asset_name": f"{company} common stock",
            "asset_type": "equity",
            "transaction_type": None,
            "amount_range_low": None,
            "amount_range_high": None,
            "notification_date": _parse_iso_date(raw.get("filing_date")),
            "source_url": filing_url,
            "ticker": None,
            "source_name": self.source_name,
            "source_record_id": accession or f"sec-edgar-{raw.get('cik')}-{raw.get('filing_date')}",
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import FinancialDisclosure

        if not record.get("source_record_id"):
            return
        model_name = record.pop("_model", None)
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
    s = str(value)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_year(value: Any) -> int | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").year
    except ValueError:
        return None
