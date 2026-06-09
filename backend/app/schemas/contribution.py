from datetime import date

from pydantic import BaseModel


class ContributionOut(BaseModel):
    id: int
    donor_name: str
    donor_type: str
    recipient_name: str
    committee_id: str | None = None
    amount: float
    date: date | None = None
    election_cycle: int | None = None
    fec_filing_id: str | None = None
    amendment_indicator: str | None = None
    employer: str | None = None
    occupation: str | None = None
    location: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class ContributionListOut(BaseModel):
    items: list[ContributionOut]
    total: int
    page: int
    per_page: int


class ContributionSummary(BaseModel):
    total_amount: float
    total_count: int
    by_cycle: dict[str, float]
    by_donor_type: dict[str, float]
