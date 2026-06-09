from pydantic import BaseModel


class LobbyingRecordOut(BaseModel):
    id: int
    lda_id: str
    registrant_name: str
    client_name: str | None = None
    lobbyist_name: str | None = None
    issue_area: str | None = None
    issue_text: str | None = None
    amount: float | None = None
    report_quarter: str | None = None
    filing_type: str | None = None
    government_entities_lobbied: str | None = None
    source_xml_url: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class LobbyingRecordListOut(BaseModel):
    items: list[LobbyingRecordOut]
    total: int
    page: int
    per_page: int


class LobbyingSummary(BaseModel):
    total_amount: float
    total_count: int
    by_issue_area: dict[str, float]
    by_quarter: dict[str, float]
