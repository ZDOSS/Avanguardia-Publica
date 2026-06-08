from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
import json

from app.core.database import get_db
from app.models import Politician
from app.schemas.politician import PoliticianOut, PoliticianListOut

router = APIRouter(prefix="/api/politicians", tags=["politicians"])


@router.get("", response_model=PoliticianListOut)
def list_politicians(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    state: str | None = Query(None, min_length=2, max_length=2),
    chamber: str | None = Query(None),
    party: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Politician)

    if state:
        query = query.filter(Politician.state == state.upper())
    if chamber:
        query = query.filter(Politician.chamber == chamber.lower())
    if search:
        query = query.filter(Politician.full_name.ilike(f"%{search}%"))
    if party:
        party_json = json.dumps([{"party": party.upper()}])
        query = query.filter(
            cast(Politician.party_history, JSONB).op("@>")(cast(party_json, JSONB))
        )

    total = query.count()
    offset = (page - 1) * per_page
    politicians = query.order_by(Politician.full_name).offset(offset).limit(per_page).all()

    return PoliticianListOut(
        items=[PoliticianOut.model_validate(p) for p in politicians],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{politician_id}", response_model=PoliticianOut)
def get_politician(politician_id: int, db: Session = Depends(get_db)):
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")
    return PoliticianOut.model_validate(politician)
