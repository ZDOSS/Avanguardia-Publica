import asyncio

from app.core.celery_app import celery_app


@celery_app.task(name="etl.sync_source", bind=True, max_retries=3, default_retry_delay=300)
def sync_source(self, source_name: str):
    """Trigger a full ETL sync for a named source."""
    from app.etl.fec import FECAdapter
    from app.etl.congress_gov import CongressGovAdapter

    adapters = {
        "fec_api": FECAdapter(),
        "congress_gov_api": CongressGovAdapter(),
    }
    adapter = adapters.get(source_name)
    if not adapter:
        return {"status": "error", "message": f"Unknown source: {source_name}"}

    return asyncio.run(adapter.run_sync())


@celery_app.task(name="etl.sync_all_sources")
def sync_all_sources():
    """Run all registered source syncs."""
    from app.models import Source
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        sources = db.query(Source).all()
        for source in sources:
            sync_source.delay(source.name)
    finally:
        db.close()
