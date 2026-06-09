from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.models import Contribution, Politician, Source

router = APIRouter(prefix="/api/admin", tags=["admin"])


class SourceHealth(BaseModel):
    name: str
    status: str
    last_synced_at: datetime | None
    sync_interval: str | None
    total_records: int
    error_count: int
    last_error: str | None
    stale: bool


class SourceHealthResponse(BaseModel):
    sources: list[SourceHealth]
    summary: dict


@router.get("/sources", response_model=SourceHealthResponse, dependencies=[Depends(require_admin)])
def sources_health(db: Session = Depends(get_db)):
    """Per-source health snapshot for the admin dashboard.

    A source is considered ``stale`` when ``last_synced_at`` is older than
    twice its declared ``sync_interval``, or — for sources that have never
    reported a sync — when there are zero ingested records in tables that
    own that source's data.
    """
    now = datetime.now(UTC)
    sources = db.query(Source).order_by(Source.name).all()

    # Per-source ownership of source_name-tagged tables. ``None`` means
    # the source owns a table that doesn't carry source_name (lobbying,
    # financial_disclosure, government_contract) — we report the
    # ``Source.total_records`` counter instead.
    source_table_map = {
        "fec_api": Contribution,
        "opensecrets_bulk": Contribution,
        "congress_gov_api": Politician,
        "voteview": Politician,
        "senate_lda": None,
        "house_clerk": None,
        "usaspending": None,
        "sec_edgar": None,
        "quiver_quant": None,
        "canada_elections": Politician,
        "ca_calaccess": Politician,
    }

    health: list[SourceHealth] = []
    for source in sources:
        record_count = 0
        table = source_table_map.get(source.name)
        if table is not None and hasattr(table, "source_name"):
            record_count = (
                db.query(func.count(table.id))
                .filter(table.source_name == source.name)
                .scalar()
                or 0
            )

        interval_hours = _parse_interval_hours(source.sync_interval)
        stale = False
        if source.last_synced_at is None:
            stale = record_count == 0
        elif interval_hours is not None:
            stale = (now - source.last_synced_at) > timedelta(hours=interval_hours * 2)

        errors = source.errors or []
        health.append(
            SourceHealth(
                name=source.name,
                status=source.status,
                last_synced_at=source.last_synced_at,
                sync_interval=source.sync_interval,
                total_records=source.total_records or 0,
                error_count=len(errors),
                last_error=errors[-1] if errors else None,
                stale=stale,
            )
        )

    healthy = sum(1 for s in health if not s.stale and s.status == "completed")
    failing = sum(1 for s in health if s.status == "failed")
    stale_count = sum(1 for s in health if s.stale)
    summary = {
        "total": len(health),
        "healthy": healthy,
        "failing": failing,
        "stale": stale_count,
        "total_records_ingested": sum(s.total_records for s in health),
    }

    return SourceHealthResponse(sources=health, summary=summary)


def _parse_interval_hours(interval: str | None) -> float | None:
    """Parse ``"daily"`` / ``"6h"`` / ``"30m"`` to hours, or None on miss.

    Returns a float so sub-hour intervals (e.g. ``"5m"``) keep their
    precision; the stale check then compares against a 2× multiple that
    scales with the source's declared cadence.
    """
    if not interval:
        return None
    interval = interval.strip().lower()
    if interval == "daily":
        return 24.0
    if interval == "hourly":
        return 1.0
    if interval == "weekly":
        return 24.0 * 7
    if interval.endswith("h"):
        try:
            return float(int(interval[:-1]))
        except ValueError:
            return None
    if interval.endswith("m"):
        try:
            return int(interval[:-1]) / 60.0
        except ValueError:
            return None
    return None
