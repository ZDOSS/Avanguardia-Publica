from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routers import politicians, voting

app = FastAPI(title="Avanguardia Publica API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(politicians.router)
app.include_router(voting.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
