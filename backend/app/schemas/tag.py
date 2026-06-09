
from pydantic import BaseModel


class TagOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    is_admin_only: bool

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str
    slug: str
    description: str | None = None
    is_admin_only: bool = True


class TagUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_admin_only: bool | None = None


class PoliticianTagOut(BaseModel):
    tag: TagOut
    created_at: str


class PoliticianTagsResponse(BaseModel):
    politician_id: int
    tags: list[TagOut]
