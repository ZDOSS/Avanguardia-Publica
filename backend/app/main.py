import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    admin,
    contracts,
    contributions,
    financials,
    lobbying,
    organizations,
    politicians,
    search,
    tags,
    voting,
)
from app.core.cache import get_client
from app.core.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Avanguardia Publica API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(politicians.router)
app.include_router(voting.router)
app.include_router(contributions.router)
app.include_router(lobbying.router)
app.include_router(financials.router)
app.include_router(contracts.router)
app.include_router(organizations.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(tags.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/health/ready")
def readiness():
    """Readiness check: verifies DB and (optionally) Redis are reachable.

    The DB error message is logged server-side and replaced with a
    generic ``"error"`` string in the response body so internal network
    details (hostnames, ports, driver internals) never leak to public
    callers.
    """
    from sqlalchemy import text

    from app.core.database import SessionLocal

    db_status = "ok"
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception:
        logger.exception("Readiness check: database connection failed")
        db_status = "error"

    redis_status = "ok" if get_client() is not None else "unavailable"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "redis": redis_status,
    }
