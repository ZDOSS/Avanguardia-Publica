import httpx
from app.core.config import settings
from app.etl.base import BaseSourceAdapter


class FECAdapter(BaseSourceAdapter):
    source_name = "fec_api"
    base_url = "https://api.open.fec.gov/v1"
    max_pages_default = 50  # safety cap per sync run

    async def fetch_records(self, max_pages: int | None = None) -> list[dict]:
        """Fetch contributions from FEC API with pagination and safety cap."""
        max_pages = max_pages or self.max_pages_default
        records = []
        async with httpx.AsyncClient() as client:
            page = 1
            while page <= max_pages:
                resp = await client.get(
                    f"{self.base_url}/schedules/schedule_a/",
                    params={
                        "api_key": settings.api_key_data_gov,
                        "per_page": 100,
                        "page": page,
                        "sort": "-contribution_receipt_date",
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results", [])
                records.extend(results)
                total_pages = data.get("pagination", {}).get("pages", 1)
                if page >= total_pages or not results:
                    break
                page += 1
        return records

    def normalize(self, raw: dict) -> dict:
        return {
            "donor_name": raw.get("contributor_name", ""),
            "donor_type": raw.get("contributor_type", "individual"),
            "recipient_name": raw.get("committee_name", ""),
            "committee_id": raw.get("committee_id", ""),
            "amount": float(raw.get("contribution_receipt_amount", 0)),
            "date": raw.get("contribution_receipt_date"),
            "election_cycle": raw.get("cycle"),
            "fec_filing_id": raw.get("fec_filing_id"),
            "amendment_indicator": raw.get("amendment_indicator"),
            "employer": raw.get("contributor_employer"),
            "occupation": raw.get("contributor_occupation"),
            "location": f"{raw.get('contributor_city', '')}, {raw.get('contributor_state', '')}",
            "source_name": self.source_name,
            "source_record_id": str(raw.get("sub_id", raw.get("fec_filing_id", ""))),
        }

    async def _upsert(self, record: dict, db=None) -> None:
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(self._model).values(**record)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_contribution_dedup",
            set_={k: stmt.excluded[k] for k in record if k not in ("source_name", "source_record_id")},
        )
        db.execute(stmt)

    _model = None  # set lazily to avoid import cycle


# Lazy import to avoid circular deps
from app.models import Contribution

FECAdapter._model = Contribution
