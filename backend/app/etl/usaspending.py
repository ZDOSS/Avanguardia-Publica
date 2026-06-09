"""USAspending.gov government contracts adapter.

Source: https://api.usaspending.gov/
Auth:   none (public)

USAspending publishes federal contract and grant award data. The
``/api/v2/search/spending_by_award/`` endpoint paginates over a multi-year
window with award-type filters. We pull federal contract awards
(award_type_codes=['A','B','C','D']) for the most recent 2 fiscal years and
store each as a GovernmentContract row.

Strategy:
- POST-based paginated search; per_page=100, max_pages cap.
- Map NAICS, awarding agency, recipient, and award amount to the model.
- politician_id is resolved only when the recipient is a known org whose
  linked politicians are tracked separately (out of scope for this adapter).
"""

from datetime import datetime, timezone
from typing import Any

import httpx

from app.etl.base import BaseSourceAdapter


class USASpendingAdapter(BaseSourceAdapter):
    """Federal contract awards from USAspending.gov."""

    source_name = "usaspending"
    base_url = "https://api.usaspending.gov/api/v2"
    max_pages_default = 10  # 10 × 100 = 1000 contracts per run, safe cap

    async def fetch_records(self, fiscal_year: int | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        target_years = [fiscal_year] if fiscal_year else self._recent_fy(2)
        async with httpx.AsyncClient() as client:
            for fy in target_years:
                page = 1
                pages_fetched = 0
                while pages_fetched < self.max_pages_default:
                    payload = {
                        "filters": {
                            "award_type_codes": ["A", "B", "C", "D"],
                            "time_period": [{"start_date": f"{fy - 1}-10-01", "end_date": f"{fy}-09-30"}],
                        },
                        "fields": [
                            "Award ID",
                            "Recipient Name",
                            "Awarding Agency",
                            "Award Amount",
                            "Award Date",
                            "Description",
                            "NAICS Code",
                            "Place of Performance City Name",
                            "Place of Performance State Code",
                        ],
                        "page": page,
                        "limit": 100,
                        "sort": "Award Amount",
                        "order": "desc",
                    }
                    try:
                        resp = await client.post(
                            f"{self.base_url}/search/spending_by_award/",
                            json=payload,
                            timeout=60,
                        )
                        resp.raise_for_status()
                    except httpx.HTTPStatusError:
                        break
                    data = resp.json()
                    results = data.get("results", [])
                    if not results:
                        break
                    records.extend(results)
                    if len(results) < 100:
                        break
                    page += 1
                    pages_fetched += 1
        return records

    def _recent_fy(self, count: int) -> list[int]:
        # US federal fiscal year runs Oct 1 – Sep 30. FY year is named
        # after the calendar year in which it ENDS:
        # - Jan..Sep 2026  → FY2026 (ends Sep 30 2026)
        # - Oct..Dec 2026  → FY2027 (ends Sep 30 2027)
        now = datetime.now(timezone.utc)
        fy = now.year + 1 if now.month >= 10 else now.year
        return [fy - i for i in range(count)]

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map a USAspending result row to GovernmentRecord shape."""
        award_id = str(raw.get("Award ID") or raw.get("internal_id") or "")
        pop_city = raw.get("Place of Performance City Name") or ""
        pop_state = raw.get("Place of Performance State Code") or ""
        place = ", ".join(p for p in (pop_city, pop_state) if p) or None
        return {
            "_model": "GovernmentContract",
            "award_id": award_id,
            "recipient_name": raw.get("Recipient Name", ""),
            "awarding_agency": raw.get("Awarding Agency"),
            "amount": _safe_float(raw.get("Award Amount")),
            "award_date": _parse_iso_date(raw.get("Award Date")),
            "description": raw.get("Description"),
            "naics_code": raw.get("NAICS Code"),
            "place_of_performance": place,
            "source_name": self.source_name,
            "source_record_id": award_id or f"usaspending-{raw.get('Recipient Name')}-{raw.get('Award Date')}",
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import GovernmentContract

        if not record.get("source_record_id"):
            return
        model_name = record.pop("_model", None)
        existing = db.query(GovernmentContract).filter(
            GovernmentContract.source_name == record["source_name"],
            GovernmentContract.source_record_id == record["source_record_id"],
        ).first()
        if existing:
            for k, v in record.items():
                setattr(existing, k, v)
        else:
            db.add(GovernmentContract(**record))


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_date(value: Any):
    if not value:
        return None
    s = str(value)
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
