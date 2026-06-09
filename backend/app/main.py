from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routers import politicians, voting, contributions, lobbying, financials, contracts, organizations

app = FastAPI(title="Avanguardia Publica API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(politicians.router)
app.include_router(voting.router)
app.include_router(contributions.router)
app.include_router(lobbying.router)
app.include_router(financials.router)
app.include_router(contracts.router)
app.include_router(organizations.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
