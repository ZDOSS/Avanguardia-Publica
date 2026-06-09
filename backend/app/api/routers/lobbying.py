from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import LobbyingRecord
from app.schemas.lobbying import LobbyingRecordListOut, LobbyingRecordOut, LobbyingSummary

router = APIRouter(prefix="/api/lobbying-records", tags=["lobbying"])


@router.get("", response_model=LobbyingRecordListOut)
def list_lobbying_records(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    registrant_name: str | None = Query(None),
    client_name: str | None = Query(None),
    issue_area: str | None = Query(None),
    report_quarter: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(LobbyingRecord)
    if registrant_name:
        query = query.filter(LobbyingRecord.registrant_name.ilike(f"%{registrant_name}%"))
    if client_name:
        query = query.filter(LobbyingRecord.client_name.ilike(f"%{client_name}%"))
    if issue_area:
        query = query.filter(LobbyingRecord.issue_area == issue_area)
    if report_quarter:
        query = query.filter(LobbyingRecord.report_quarter == report_quarter)

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(LobbyingRecord.report_quarter.desc()).offset(offset).limit(per_page).all()

    return LobbyingRecordListOut(
        items=[LobbyingRecordOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/summary", response_model=LobbyingSummary)
def get_lobbying_summary(db: Session = Depends(get_db)):
    total_amount = db.query(func.sum(LobbyingRecord.amount)).scalar() or 0.0
    total_count = db.query(LobbyingRecord).count()

    issue_query = db.query(
        LobbyingRecord.issue_area,
        func.sum(LobbyingRecord.amount),
    ).group_by(LobbyingRecord.issue_area)
    by_issue_area = {str(row[0]): float(row[1] or 0) for row in issue_query.all() if row[0]}

    quarter_query = db.query(
        LobbyingRecord.report_quarter,
        func.sum(LobbyingRecord.amount),
    ).group_by(LobbyingRecord.report_quarter)
    by_quarter = {str(row[0]): float(row[1] or 0) for row in quarter_query.all() if row[0]}

    return LobbyingSummary(
        total_amount=float(total_amount),
        total_count=total_count,
        by_issue_area=by_issue_area,
        by_quarter=by_quarter,
    )
