from datetime import date, datetime
from pydantic import BaseModel
from typing import Any


class VotingRecordOut(BaseModel):
    id: int
    politician_id: int
    roll_call_number: int
    congress: int
    session: int
    chamber: str
    bill_id: str | None = None
    bill_title: str | None = None
    bill_type: str | None = None
    bill_number: str | None = None
    vote: str
    vote_date: date | None = None
    issue_area: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class VotingRecordListOut(BaseModel):
    items: list[VotingRecordOut]
    total: int
    page: int
    per_page: int


class IdeologyScoreOut(BaseModel):
    id: int
    politician_id: int
    congress: int
    chamber: str
    dw_nominate_dim1: float | None = None
    dw_nominate_dim2: float | None = None
    source_name: str

    model_config = {"from_attributes": True}


class IdeologyScoreListOut(BaseModel):
    items: list[IdeologyScoreOut]
    total: int
    page: int
    per_page: int


class PoliticianVoteStats(BaseModel):
    total_votes: int
    yea_count: int
    nay_count: int
    present_count: int
    not_voting_count: int
    attendance_rate: float
    ideology_dim1: float | None = None
    ideology_dim2: float | None = None
