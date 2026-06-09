import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.cache import cache_json
from app.core.database import get_db
from app.models import Contribution, FinancialDisclosure, Politician, VotingRecord
from app.schemas.contribution import ContributionOut
from app.schemas.financial import FinancialDisclosureOut
from app.schemas.politician import PoliticianListOut, PoliticianOut
from app.schemas.voting import VotingRecordOut

router = APIRouter(prefix="/api/politicians", tags=["politicians"])


@router.get("", response_model=PoliticianListOut)
@cache_json("politicians:list", ttl_seconds=60)
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

    return {
        "items": [PoliticianOut.model_validate(p).model_dump() for p in politicians],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/{politician_id}", response_model=PoliticianOut)
def get_politician(politician_id: int, db: Session = Depends(get_db)):
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")
    return PoliticianOut.model_validate(politician)


@router.get("/{politician_id}/voting", response_model=list[VotingRecordOut])
def get_politician_voting(
    politician_id: int,
    congress: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")

    query = db.query(VotingRecord).filter(VotingRecord.politician_id == politician_id)
    if congress:
        query = query.filter(VotingRecord.congress == congress)
    records = query.order_by(VotingRecord.vote_date.desc()).limit(limit).all()
    return [VotingRecordOut.model_validate(r) for r in records]


@router.get("/{politician_id}/contributions", response_model=list[ContributionOut])
def get_politician_contributions(
    politician_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")

    records = db.query(Contribution).filter(
        Contribution.politician_id == politician_id
    ).order_by(Contribution.date.desc()).limit(limit).all()
    return [ContributionOut.model_validate(r) for r in records]


@router.get("/{politician_id}/financials", response_model=list[FinancialDisclosureOut])
def get_politician_financials(
    politician_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Stock trades, asset disclosures, and STOCK Act transactions for a politician."""
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")

    records = (
        db.query(FinancialDisclosure)
        .filter(FinancialDisclosure.politician_id == politician_id)
        .order_by(FinancialDisclosure.notification_date.desc().nullslast())
        .limit(limit)
        .all()
    )
    return [FinancialDisclosureOut.model_validate(r) for r in records]
