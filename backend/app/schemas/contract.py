from datetime import date

from pydantic import BaseModel


class GovernmentContractOut(BaseModel):
    id: int
    award_id: str
    recipient_name: str
    awarding_agency: str | None = None
    amount: float | None = None
    award_date: date | None = None
    description: str | None = None
    naics_code: str | None = None
    place_of_performance: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class GovernmentContractListOut(BaseModel):
    items: list[GovernmentContractOut]
    total: int
    page: int
    per_page: int


class GovernmentContractSummary(BaseModel):
    total_amount: float
    total_count: int
    by_agency: dict[str, float]
    by_year: dict[str, float]
