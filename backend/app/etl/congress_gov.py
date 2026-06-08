import httpx
from app.core.config import settings
from app.etl.base import BaseSourceAdapter


class CongressGovAdapter(BaseSourceAdapter):
    source_name = "congress_gov_api"
    base_url = "https://api.congress.gov/v3"

    async def fetch_records(self) -> list[dict]:
        """Fetch current members from Congress.gov with pagination."""
        records = []
        async with httpx.AsyncClient() as client:
            for chamber in ("house", "senate"):
                offset = 0
                while True:
                    resp = await client.get(
                        f"{self.base_url}/member/congress/current/{chamber}",
                        params={
                            "api_key": settings.api_key_data_gov,
                            "limit": 250,
                            "offset": offset,
                        },
                        timeout=30,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    members = data.get("members", [])
                    if not members:
                        break
                    records.extend(members)
                    offset += len(members)
        return records

    def normalize(self, raw: dict) -> dict:
        party_history = []
        party_entries = raw.get("partyHistory", [])
        for entry in party_entries:
            party_history.append({
                "party": entry.get("partyAbbreviation", entry.get("partyName", "")),
                "start_date": entry.get("startDate"),
                "end_date": entry.get("endDate"),
            })

        name_parts = (raw.get("name", "")).split(",")
        last_name = name_parts[0].strip() if name_parts else ""
        first_middle = name_parts[1].strip() if len(name_parts) > 1 else ""
        first_parts = first_middle.split()
        first_name = first_parts[0] if first_parts else ""
        middle_name = " ".join(first_parts[1:]) if len(first_parts) > 1 else None

        return {
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "full_name": raw.get("directOrderName", raw.get("name", "")),
            "party_history": party_history,
            "state": raw.get("state", "").upper(),
            "district": raw.get("district"),
            "chamber": raw.get("chamber", "").lower(),
            "bioguide_id": raw.get("bioguideId"),
            "in_office": True,
            "photo_url": raw.get("depiction", {}).get("imageUrl") if isinstance(raw.get("depiction"), dict) else None,
        }

    async def _upsert(self, record: dict, db=None) -> None:
        from app.models import Politician

        bioguide = record.get("bioguide_id")
        if not bioguide:
            db.add(Politician(**record))
            return

        existing = db.query(Politician).filter(Politician.bioguide_id == bioguide).first()
        if existing:
            for k, v in record.items():
                if v is not None:
                    setattr(existing, k, v)
        else:
            db.add(Politician(**record))
