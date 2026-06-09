from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Contribution, Organization, Politician, VotingRecord
from app.schemas.search import SearchResponse, SearchResultItem

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Cross-entity full-text search using PostgreSQL ``to_tsquery``.

    Runs four parallel GIN-backed ``tsvector`` lookups (politician, org,
    contribution, voting_record) and returns a ranked, merged result set.
    Uses ``websearch_to_tsquery`` so callers can pass natural-language
    queries like ``"climate -carbon"`` or ``"tax reform OR tariffs"``.
    """
    ts_query = func.websearch_to_tsquery("english", q)
    per_entity_limit = max(5, limit // 4 + 1)

    # True per-entity match counts. Run as cheap aggregate COUNT(*) queries
    # against the same GIN-indexed condition; the items[] slice above is
    # capped at per_entity_limit for ranking, but the client can show the
    # real total without us re-running the full text search.
    politician_total = (
        db.query(func.count(Politician.id))
        .filter(Politician.search_tsv.op("@@")(ts_query))
        .scalar()
        or 0
    )
    org_total = (
        db.query(func.count(Organization.id))
        .filter(Organization.search_tsv.op("@@")(ts_query))
        .scalar()
        or 0
    )
    contribution_total = (
        db.query(func.count(Contribution.id))
        .filter(Contribution.search_tsv.op("@@")(ts_query))
        .scalar()
        or 0
    )
    voting_total = (
        db.query(func.count(VotingRecord.id))
        .filter(VotingRecord.search_tsv.op("@@")(ts_query))
        .scalar()
        or 0
    )

    politician_rows = (
        db.query(
            Politician.id,
            Politician.full_name,
            func.ts_rank(Politician.search_tsv, ts_query).label("rank"),
        )
        .filter(Politician.search_tsv.op("@@")(ts_query))
        .order_by(text("rank desc"))
        .limit(per_entity_limit)
        .all()
    )

    org_rows = (
        db.query(
            Organization.id,
            Organization.name,
            func.ts_rank(Organization.search_tsv, ts_query).label("rank"),
        )
        .filter(Organization.search_tsv.op("@@")(ts_query))
        .order_by(text("rank desc"))
        .limit(per_entity_limit)
        .all()
    )

    contribution_rows = (
        db.query(
            Contribution.id,
            Contribution.donor_name,
            Contribution.recipient_name,
            func.ts_rank(Contribution.search_tsv, ts_query).label("rank"),
        )
        .filter(Contribution.search_tsv.op("@@")(ts_query))
        .order_by(text("rank desc"))
        .limit(per_entity_limit)
        .all()
    )

    voting_rows = (
        db.query(
            VotingRecord.id,
            VotingRecord.bill_title,
            func.ts_rank(VotingRecord.search_tsv, ts_query).label("rank"),
        )
        .filter(VotingRecord.search_tsv.op("@@")(ts_query))
        .order_by(text("rank desc"))
        .limit(per_entity_limit)
        .all()
    )

    items: list[SearchResultItem] = []
    for row in politician_rows:
        items.append(
            SearchResultItem(
                entity_type="politician",
                entity_id=row.id,
                title=row.full_name,
                subtitle="Politician",
                url=f"/politician/{row.id}",
                rank=float(row.rank or 0),
            )
        )
    for row in org_rows:
        items.append(
            SearchResultItem(
                entity_type="organization",
                entity_id=row.id,
                title=row.name,
                subtitle="Organization",
                url=f"/organization/{row.id}",
                rank=float(row.rank or 0),
            )
        )
    for row in contribution_rows:
        subtitle = f"{row.donor_name} → {row.recipient_name}"
        items.append(
            SearchResultItem(
                entity_type="contribution",
                entity_id=row.id,
                title=row.donor_name or "Unknown donor",
                subtitle=subtitle,
                url=None,
                rank=float(row.rank or 0),
            )
        )
    for row in voting_rows:
        items.append(
            SearchResultItem(
                entity_type="voting_record",
                entity_id=row.id,
                title=row.bill_title or "Untitled bill",
                subtitle="Vote",
                url=None,
                rank=float(row.rank or 0),
            )
        )

    items.sort(key=lambda item: item.rank, reverse=True)
    total = politician_total + org_total + contribution_total + voting_total
    items = items[:limit]

    return SearchResponse(query=q, total=total, items=items)
