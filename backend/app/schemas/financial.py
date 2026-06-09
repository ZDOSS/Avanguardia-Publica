from datetime import date
from pydantic import BaseModel


class FinancialDisclosureOut(BaseModel):
    id: int
    # Nullable: SEC EDGAR Form 4 records are corporate insiders, not
    # politicians. Quiver Quant rows that don't match a legislator are
    # also stored without politician_id for later admin resolution.
    politician_id: int | None = None
    filing_year: int | None = None
    filing_type: str | None = None
    asset_name: str | None = None
    asset_type: str | None = None
    transaction_type: str | None = None
    amount_range_low: float | None = None
    amount_range_high: float | None = None
    notification_date: date | None = None
    source_url: str | None = None
    ticker: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class FinancialDisclosureListOut(BaseModel):
    items: list[FinancialDisclosureOut]
    total: int
    page: int
    per_page: int


class FinancialDisclosureSummary(BaseModel):
    total_count: int
    by_ticker: dict[str, int]
    by_transaction_type: dict[str, int]
    by_year: dict[str, int]
