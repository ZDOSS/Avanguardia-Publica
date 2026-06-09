
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.models import Politician, PoliticianTag, Tag
from app.schemas.tag import (
    PoliticianTagOut,
    PoliticianTagsResponse,
    TagCreate,
    TagOut,
    TagUpdate,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/tags", response_model=list[TagOut], dependencies=[Depends(require_admin)])
def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).order_by(Tag.name).all()


@router.post(
    "/tags",
    response_model=TagOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    if not payload.slug.strip() or not payload.name.strip():
        raise HTTPException(status_code=422, detail="name and slug are required")
    tag = Tag(
        name=payload.name.strip(),
        slug=payload.slug.strip().lower(),
        description=payload.description,
        is_admin_only=payload.is_admin_only,
    )
    db.add(tag)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Tag with slug '{payload.slug}' already exists") from e
    db.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=TagOut, dependencies=[Depends(require_admin)])
def update_tag(tag_id: int, payload: TagUpdate, db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    # ``exclude_unset=True`` distinguishes a missing field from an explicit
    # null, so an admin can clear ``description`` by sending
    # ``{"description": null}`` rather than having the call silently no-op.
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(tag, field, value)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()


@router.put(
    "/politicians/{politician_id}/tags/{tag_id}",
    response_model=PoliticianTagOut,
    dependencies=[Depends(require_admin)],
)
def attach_tag(politician_id: int, tag_id: int, db: Session = Depends(get_db)):
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    link = (
        db.query(PoliticianTag)
        .filter(
            PoliticianTag.politician_id == politician_id,
            PoliticianTag.tag_id == tag_id,
        )
        .first()
    )
    if link is None:
        link = PoliticianTag(politician_id=politician_id, tag_id=tag_id)
        db.add(link)
        db.commit()
        db.refresh(link)
    return PoliticianTagOut(
        tag=TagOut.model_validate(tag),
        created_at=link.created_at.isoformat(),
    )


@router.delete(
    "/politicians/{politician_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def detach_tag(politician_id: int, tag_id: int, db: Session = Depends(get_db)):
    link = (
        db.query(PoliticianTag)
        .filter(
            PoliticianTag.politician_id == politician_id,
            PoliticianTag.tag_id == tag_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Tag is not attached to this politician")
    db.delete(link)
    db.commit()


@router.get(
    "/politicians/{politician_id}/tags",
    response_model=PoliticianTagsResponse,
)
def list_politician_tags(politician_id: int, db: Session = Depends(get_db)):
    """Public read endpoint — anyone can see which tags a politician carries.

    Tag creation, attachment, and detachment are gated by ``require_admin``.
    """
    politician = db.query(Politician).filter(Politician.id == politician_id).first()
    if not politician:
        raise HTTPException(status_code=404, detail="Politician not found")
    rows = (
        db.query(Tag)
        .join(PoliticianTag, PoliticianTag.tag_id == Tag.id)
        .filter(
            PoliticianTag.politician_id == politician_id,
            Tag.is_admin_only == False,  # noqa: E712
        )
        .order_by(Tag.name)
        .all()
    )
    return PoliticianTagsResponse(
        politician_id=politician_id,
        tags=[TagOut.model_validate(t) for t in rows],
    )
