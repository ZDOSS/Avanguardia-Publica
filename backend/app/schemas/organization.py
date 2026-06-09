from pydantic import BaseModel


class OrganizationOut(BaseModel):
    id: int
    name: str
    type: str
    fec_id: str | None = None
    opensecrets_id: str | None = None
    source_name: str
    source_record_id: str

    model_config = {"from_attributes": True}


class OrganizationListOut(BaseModel):
    items: list[OrganizationOut]
    total: int
    page: int
    per_page: int


class OrganizationFlowLink(BaseModel):
    target: str
    target_type: str  # "politician" | "organization" | "recipient"
    weight: float
    count: int
