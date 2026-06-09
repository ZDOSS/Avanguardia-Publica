from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Contribution
from app.schemas.contribution import ContributionListOut, ContributionOut, ContributionSummary

router = APIRouter(prefix="/api/contributions", tags=["contributions"])


@router.get("", response_model=ContributionListOut)
def list_contributions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    politician_id: int | None = Query(None),
    donor_name: str | None = Query(None),
    committee_id: str | None = Query(None),
    election_cycle: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Contribution)

    if politician_id:
        query = query.filter(Contribution.politician_id == politician_id)
    if donor_name:
        query = query.filter(Contribution.donor_name.ilike(f"%{donor_name}%"))
    if committee_id:
        query = query.filter(Contribution.committee_id == committee_id)
    if election_cycle:
        query = query.filter(Contribution.election_cycle == election_cycle)

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(Contribution.date.desc()).offset(offset).limit(per_page).all()

    return ContributionListOut(
        items=[ContributionOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/summary", response_model=ContributionSummary)
def get_contribution_summary(
    politician_id: int | None = Query(None),
    election_cycle: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Contribution)
    if politician_id:
        query = query.filter(Contribution.politician_id == politician_id)
    if election_cycle:
        query = query.filter(Contribution.election_cycle == election_cycle)

    total_amount = db.query(func.sum(Contribution.amount)).select_from(query.subquery()).scalar() or 0.0
    total_count = query.count()

    # By cycle
    cycle_query = db.query(
        Contribution.election_cycle,
        func.sum(Contribution.amount)
    ).group_by(Contribution.election_cycle)
    if politician_id:
        cycle_query = cycle_query.filter(Contribution.politician_id == politician_id)
    if election_cycle:
        cycle_query = cycle_query.filter(Contribution.election_cycle == election_cycle)
    by_cycle = {str(row[0]): float(row[1] or 0) for row in cycle_query.all() if row[0]}

    # By donor type
    type_query = db.query(
        Contribution.donor_type,
        func.sum(Contribution.amount)
    ).group_by(Contribution.donor_type)
    if politician_id:
        type_query = type_query.filter(Contribution.politician_id == politician_id)
    if election_cycle:
        type_query = type_query.filter(Contribution.election_cycle == election_cycle)
    by_donor_type = {str(row[0]): float(row[1] or 0) for row in type_query.all() if row[0]}

    return ContributionSummary(
        total_amount=float(total_amount),
        total_count=total_count,
        by_cycle=by_cycle,
        by_donor_type=by_donor_type,
    )
