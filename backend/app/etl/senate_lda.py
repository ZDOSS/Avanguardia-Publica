"""Senate LDA (Lobbying Disclosure Act) API adapter for lobbying records.

Source: https://lda.senate.gov/api/v1/
Auth:   SENATE_LDA_API_KEY env var (set in .env / Docker secrets)

The Senate LDA publishes quarterly lobbying filings (LD-1, LD-2, LD-201)
covering all federally registered lobbyists. Filings include registrant,
client, lobbyist names, government entities lobbied, and reported income.

Strategy:
- Pull contributions from the public bulk dataset endpoint.
- Cap pagination via max_pages_default to avoid OOM on the full filing set.
- Each filing's ``filing_uuid`` becomes the stable ``source_record_id``.
"""

import httpx
from typing import Any

from app.core.config import settings
from app.etl.base import BaseSourceAdapter


class SenateLDAAdapter(BaseSourceAdapter):
    """Lobbying disclosure filings from the Senate LDA bulk API."""

    source_name = "senate_lda"
    base_url = "https://lda.senate.gov/api/v1"
    max_pages_default = 20  # 20 pages × 250 = 5000 filings, safe cap

    async def fetch_records(self, filing_year: int | None = None) -> list[dict[str, Any]]:
        """Fetch LDA filings, optionally filtered by year."""
        records: list[dict[str, Any]] = []
        if not settings.senate_lda_api_key:
            return records

        async with httpx.AsyncClient() as client:
            offset = 0
            pages_fetched = 0
            while pages_fetched < self.max_pages_default:
                # NOTE: The Senate LDA REST API requires the API key as a
                # query parameter; an ``Authorization`` header is not
                # accepted. The key will appear in server access logs at
                # lda.senate.gov and any request-tracing infrastructure.
                params: dict[str, Any] = {
                    "api_key": settings.senate_lda_api_key,
                    "limit": 250,
                    "skip": offset,
                }
                if filing_year:
                    params["filing_year"] = filing_year
                # Per-page try/except: a transient 429/5xx on one page
                # must not abort the entire multi-page sync. We log via
                # the standard ``print`` channel (the base run_sync does
                # not surface fetch errors directly) and break out of the
                # loop with whatever records we collected so far.
                try:
                    resp = await client.get(
                        f"{self.base_url}/filings/",
                        params=params,
                        timeout=60,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    print(f"senate_lda: page {pages_fetched} HTTP {e.response.status_code}, stopping")
                    break
                except httpx.RequestError as e:
                    print(f"senate_lda: page {pages_fetched} request error {e}, stopping")
                    break
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    break
                records.extend(results)
                offset += len(results)
                pages_fetched += 1
                if len(results) < 250:
                    break
        return records

    def normalize(self, raw: dict) -> dict[str, Any]:
        """Map a Senate LDA filing to the unified LobbyingRecord shape."""
        filing_uuid = raw.get("filing_uuid") or raw.get("id")
        registrant = raw.get("registrant", {}) or {}
        client = raw.get("client", {}) or {}
        lobbyists = raw.get("lobbyists", []) or []
        government_entities = raw.get("government_entities", []) or []

        lobbyist_names: list[str] = []
        for lob in lobbyists:
            name = lob.get("lobbyist_name") if isinstance(lob, dict) else None
            if name:
                lobbyist_names.append(name)

        entity_names: list[str] = []
        for ent in government_entities:
            name = ent.get("name") if isinstance(ent, dict) else None
            if name:
                entity_names.append(name)

        return {
            "_model": "LobbyingRecord",
            "lda_id": str(filing_uuid or ""),
            "registrant_name": registrant.get("name", "") if isinstance(registrant, dict) else str(registrant),
            "client_name": client.get("name") if isinstance(client, dict) else None,
            "lobbyist_name": ", ".join(lobbyist_names) if lobbyist_names else None,
            "issue_area": raw.get("issue_area_description") or raw.get("general_issue_code"),
            "issue_text": raw.get("description"),
            "amount": _safe_amount(raw.get("income")),
            "report_quarter": _safe_quarter(raw.get("filing_year"), raw.get("filing_period")),
            "filing_type": raw.get("filing_type_description") or raw.get("filing_type"),
            "government_entities_lobbied": ", ".join(entity_names) if entity_names else None,
            "source_xml_url": raw.get("filing_document_url") or raw.get("pdf_url"),
            "source_name": self.source_name,
            "source_record_id": str(filing_uuid) if filing_uuid is not None else "",
        }

    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        from app.models import LobbyingRecord

        if not record.get("source_record_id"):
            return
        model_name = record.pop("_model", None)
        existing = db.query(LobbyingRecord).filter(
            LobbyingRecord.source_name == record["source_name"],
            LobbyingRecord.source_record_id == record["source_record_id"],
        ).first()
        if existing:
            for k, v in record.items():
                setattr(existing, k, v)
        else:
            db.add(LobbyingRecord(**record))


def _safe_amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_quarter(year: Any, period: Any) -> str | None:
    if not year and not period:
        return None
    y = str(year) if year else ""
    p = str(period) if period else ""
    if y and p:
        return f"{y}-{p}"
    return y or p or None
