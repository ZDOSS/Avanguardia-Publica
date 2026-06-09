
from pydantic import BaseModel


class SearchResultItem(BaseModel):
    """One result row in a cross-entity search response."""
    entity_type: str  # "politician" | "organization" | "contribution" | "voting_record"
    entity_id: int
    title: str
    subtitle: str | None = None
    url: str | None = None
    rank: float


class SearchResponse(BaseModel):
    query: str
    total: int
    items: list[SearchResultItem]
