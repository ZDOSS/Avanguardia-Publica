from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import get_db
from app.models import VotingRecord, PoliticianIdeologyScore
from app.schemas.voting import VotingRecordOut, VotingRecordListOut, IdeologyScoreOut, PoliticianVoteStats

router = APIRouter(prefix="/api/voting", tags=["voting"])


@router.get("/records", response_model=VotingRecordListOut)
def list_voting_records(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    politician_id: int | None = Query(None),
    congress: int | None = Query(None),
    chamber: str | None = Query(None),
    vote: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(VotingRecord)

    if politician_id:
        query = query.filter(VotingRecord.politician_id == politician_id)
    if congress:
        query = query.filter(VotingRecord.congress == congress)
    if chamber:
        query = query.filter(VotingRecord.chamber == chamber.lower())
    if vote:
        query = query.filter(VotingRecord.vote == vote.lower())

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(VotingRecord.vote_date.desc()).offset(offset).limit(per_page).all()

    return VotingRecordListOut(
        items=[VotingRecordOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/records/{record_id}", response_model=VotingRecordOut)
def get_voting_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(VotingRecord).filter(VotingRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Voting record not found")
    return VotingRecordOut.model_validate(record)


@router.get("/ideology-scores", response_model=IdeologyScoreOut)
def list_ideology_scores(
    politician_id: int | None = Query(None),
    congress: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(PoliticianIdeologyScore)
    if politician_id:
        query = query.filter(PoliticianIdeologyScore.politician_id == politician_id)
    if congress:
        query = query.filter(PoliticianIdeologyScore.congress == congress)
    scores = query.all()
    return [IdeologyScoreOut.model_validate(s) for s in scores]


@router.get("/politicians/{politician_id}/stats", response_model=PoliticianVoteStats)
def get_politician_vote_stats(politician_id: int, db: Session = Depends(get_db)):
    """Aggregate voting statistics for a politician."""
    total = db.query(VotingRecord).filter(VotingRecord.politician_id == politician_id).count()
    if total == 0:
        return PoliticianVoteStats(
            total_votes=0, yea_count=0, nay_count=0, present_count=0,
            not_voting_count=0, attendance_rate=0.0
        )

    yea = db.query(VotingRecord).filter(
        VotingRecord.politician_id == politician_id,
        VotingRecord.vote == "yea"
    ).count()
    nay = db.query(VotingRecord).filter(
        VotingRecord.politician_id == politician_id,
        VotingRecord.vote == "nay"
    ).count()
    present = db.query(VotingRecord).filter(
        VotingRecord.politician_id == politician_id,
        VotingRecord.vote == "present"
    ).count()
    not_voting = db.query(VotingRecord).filter(
        VotingRecord.politician_id == politician_id,
        VotingRecord.vote == "not_voting"
    ).count()

    # Latest ideology score
    latest_score = db.query(PoliticianIdeologyScore).filter(
        PoliticianIdeologyScore.politician_id == politician_id
    ).order_by(PoliticianIdeologyScore.congress.desc()).first()

    return PoliticianVoteStats(
        total_votes=total,
        yea_count=yea,
        nay_count=nay,
        present_count=present,
        not_voting_count=not_voting,
        attendance_rate=round((total - not_voting) / total, 4) if total > 0 else 0.0,
        ideology_dim1=latest_score.dw_nominate_dim1 if latest_score else None,
        ideology_dim2=latest_score.dw_nominate_dim2 if latest_score else None,
    )
