from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models import GovernmentContract
from app.schemas.contract import GovernmentContractOut, GovernmentContractListOut, GovernmentContractSummary

router = APIRouter(prefix="/api/government-contracts", tags=["contracts"])


@router.get("", response_model=GovernmentContractListOut)
def list_government_contracts(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    recipient_name: str | None = Query(None),
    awarding_agency: str | None = Query(None),
    naics_code: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(GovernmentContract)
    if recipient_name:
        query = query.filter(GovernmentContract.recipient_name.ilike(f"%{recipient_name}%"))
    if awarding_agency:
        query = query.filter(GovernmentContract.awarding_agency.ilike(f"%{awarding_agency}%"))
    if naics_code:
        query = query.filter(GovernmentContract.naics_code == naics_code)

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(GovernmentContract.award_date.desc().nullslast()).offset(offset).limit(per_page).all()

    return GovernmentContractListOut(
        items=[GovernmentContractOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/summary", response_model=GovernmentContractSummary)
def get_contracts_summary(db: Session = Depends(get_db)):
    total_amount = db.query(func.sum(GovernmentContract.amount)).scalar() or 0.0
    total_count = db.query(GovernmentContract).count()

    agency_q = db.query(
        GovernmentContract.awarding_agency, func.sum(GovernmentContract.amount)
    ).group_by(GovernmentContract.awarding_agency)
    by_agency = {str(row[0]): float(row[1] or 0) for row in agency_q.all() if row[0]}

    by_year: dict[str, float] = {}
    year_rows = db.query(
        func.extract("year", GovernmentContract.award_date),
        func.sum(GovernmentContract.amount),
    ).group_by(func.extract("year", GovernmentContract.award_date)).all()
    for row in year_rows:
        if row[0] is not None:
            by_year[str(int(row[0]))] = float(row[1] or 0)

    return GovernmentContractSummary(
        total_amount=float(total_amount),
        total_count=total_count,
        by_agency=by_agency,
        by_year=by_year,
    )
