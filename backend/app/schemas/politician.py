from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PoliticianBase(BaseModel):
    first_name: str
    middle_name: str | None = None
    last_name: str
    suffix: str | None = None
    full_name: str
    state: str
    district: str | None = None
    chamber: str
    bioguide_id: str | None = None
    in_office: bool = True
    photo_url: str | None = None
    bio_text: str | None = None


class PoliticianCreate(PoliticianBase):
    pass


class PoliticianOut(PoliticianBase):
    id: int
    fec_ids: list[str] | None = None
    icpsr_id: str | None = None
    voteview_id: str | None = None
    govtrack_id: str | None = None
    opensecrets_id: str | None = None
    party_history: list[dict[str, Any]] | None = None
    term_start: datetime | None = None
    term_end: list[datetime] | None = None
    created_at: datetime
    updated_at: datetime
    last_data_refresh: datetime | None = None

    model_config = {"from_attributes": True}


class PoliticianListOut(BaseModel):
    items: list[PoliticianOut]
    total: int
    page: int
    per_page: int
