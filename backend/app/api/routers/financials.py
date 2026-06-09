from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models import FinancialDisclosure
from app.schemas.financial import FinancialDisclosureOut, FinancialDisclosureListOut, FinancialDisclosureSummary

router = APIRouter(prefix="/api/financial-disclosures", tags=["financials"])


@router.get("", response_model=FinancialDisclosureListOut)
def list_financial_disclosures(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    politician_id: int | None = Query(None),
    ticker: str | None = Query(None),
    filing_year: int | None = Query(None),
    transaction_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(FinancialDisclosure)
    if politician_id:
        query = query.filter(FinancialDisclosure.politician_id == politician_id)
    if ticker:
        query = query.filter(FinancialDisclosure.ticker == ticker.upper())
    if filing_year:
        query = query.filter(FinancialDisclosure.filing_year == filing_year)
    if transaction_type:
        query = query.filter(FinancialDisclosure.transaction_type == transaction_type)

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(FinancialDisclosure.notification_date.desc().nullslast()).offset(offset).limit(per_page).all()

    return FinancialDisclosureListOut(
        items=[FinancialDisclosureOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/summary", response_model=FinancialDisclosureSummary)
def get_financial_summary(
    politician_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(FinancialDisclosure)
    if politician_id:
        query = query.filter(FinancialDisclosure.politician_id == politician_id)

    total_count = query.count()

    ticker_q = query.with_entities(
        FinancialDisclosure.ticker, func.count(FinancialDisclosure.id)
    ).group_by(FinancialDisclosure.ticker)
    by_ticker = {str(row[0]): int(row[1]) for row in ticker_q.all() if row[0]}

    tx_q = query.with_entities(
        FinancialDisclosure.transaction_type, func.count(FinancialDisclosure.id)
    ).group_by(FinancialDisclosure.transaction_type)
    by_transaction_type = {str(row[0]): int(row[1]) for row in tx_q.all() if row[0]}

    year_q = query.with_entities(
        FinancialDisclosure.filing_year, func.count(FinancialDisclosure.id)
    ).group_by(FinancialDisclosure.filing_year)
    by_year = {str(row[0]): int(row[1]) for row in year_q.all() if row[0]}

    return FinancialDisclosureSummary(
        total_count=total_count,
        by_ticker=by_ticker,
        by_transaction_type=by_transaction_type,
        by_year=by_year,
    )
