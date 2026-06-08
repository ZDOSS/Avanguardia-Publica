import asyncio
from datetime import datetime, timezone

from app.core.celery_app import celery_app


@celery_app.task(name="etl.sync_source", bind=True, max_retries=3, default_retry_delay=300)
def sync_source(self, source_name: str):
    """Trigger a full ETL sync for a named source."""
    from app.etl.fec import FECAdapter
    from app.etl.congress_gov import CongressGovAdapter
    from app.models import Source
    from app.core.database import SessionLocal

    adapters = {
        "fec_api": FECAdapter(),
        "congress_gov_api": CongressGovAdapter(),
    }
    adapter = adapters.get(source_name)
    if not adapter:
        return {"status": "error", "message": f"Unknown source: {source_name}"}

    result = asyncio.run(adapter.run_sync())

    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == source_name).first()
        if source is not None:
            source.last_synced_at = datetime.now(timezone.utc)
            source.total_records = result.records_upserted
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
    from app.models import Source
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        registered = ["fec_api", "congress_gov_api"]
        existing = {s.name for s in db.query(Source).all()}
        for name in registered:
            if name not in existing:
                db.add(Source(name=name, status="idle", sync_interval="daily"))
        db.commit()

        sources = db.query(Source).all()
        for source in sources:
            sync_source.delay(source.name)
    finally:
        db.close()
