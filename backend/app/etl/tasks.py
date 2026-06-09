import asyncio
from datetime import UTC, datetime

from app.core.celery_app import celery_app

REGISTERED_SOURCES = [
    "fec_api",
    "congress_gov_api",
    "voteview",
    "opensecrets_bulk",
    "senate_lda",
    "house_clerk",
    "usaspending",
    "sec_edgar",
    "quiver_quant",
]


@celery_app.task(name="etl.sync_source", bind=True, max_retries=3, default_retry_delay=300)
def sync_source(self, source_name: str):
    """Trigger a full ETL sync for a named source."""
    from app.core.database import SessionLocal
    from app.etl.congress_gov import CongressGovAdapter
    from app.etl.fec import FECAdapter
    from app.etl.house_clerk import HouseClerkAdapter
    from app.etl.opensecrets import OpenSecretsAdapter
    from app.etl.quiver_quant import QuiverQuantAdapter
    from app.etl.sec_edgar import SECEdgarAdapter
    from app.etl.senate_lda import SenateLDAAdapter
    from app.etl.usaspending import USASpendingAdapter
    from app.etl.voteview import VoteViewAdapter
    from app.models import Source

    adapters = {
        "fec_api": FECAdapter(),
        "congress_gov_api": CongressGovAdapter(),
        "voteview": VoteViewAdapter(),
        "opensecrets_bulk": OpenSecretsAdapter(),
        "senate_lda": SenateLDAAdapter(),
        "house_clerk": HouseClerkAdapter(),
        "usaspending": USASpendingAdapter(),
        "sec_edgar": SECEdgarAdapter(),
        "quiver_quant": QuiverQuantAdapter(),
    }
    adapter = adapters.get(source_name)
    if not adapter:
        return {"status": "error", "message": f"Unknown source: {source_name}"}

    result = asyncio.run(adapter.run_sync())

    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == source_name).first()
        if source is not None:
            source.last_synced_at = datetime.now(UTC)
            source.total_records = (source.total_records or 0) + result.records_upserted
            source.status = result.status
            db.commit()
    finally:
        db.close()

    return {
        "source_name": result.source_name,
        "started_at": result.started_at.isoformat(),
        "completed_at": result.completed_at.isoformat() if result.completed_at else None,
        "records_ingested": result.records_ingested,
        "records_upserted": result.records_upserted,
        "errors": result.errors,
        "status": result.status,
    }


@celery_app.task(name="etl.sync_all_sources")
def sync_all_sources():
    """Run all registered source syncs."""
    from app.core.database import SessionLocal
    from app.models import Source

    db = SessionLocal()
    try:
        existing = {s.name for s in db.query(Source).all()}
        for name in REGISTERED_SOURCES:
            if name not in existing:
                db.add(Source(name=name, status="idle", sync_interval="daily"))
        db.commit()

        sources = db.query(Source).all()
        for source in sources:
            sync_source.delay(source.name)
    finally:
        db.close()
