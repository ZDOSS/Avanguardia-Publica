from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models import Organization, Contribution
from app.schemas.organization import OrganizationOut, OrganizationListOut

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


@router.get("", response_model=OrganizationListOut)
def list_organizations(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    name: str | None = Query(None),
    type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Organization)
    if name:
        query = query.filter(Organization.name.ilike(f"%{name}%"))
    if type:
        query = query.filter(Organization.type == type)

    total = query.count()
    offset = (page - 1) * per_page
    records = query.order_by(Organization.name).offset(offset).limit(per_page).all()

    return OrganizationListOut(
        items=[OrganizationOut.model_validate(r) for r in records],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(organization_id: int, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return OrganizationOut.model_validate(org)


@router.get("/{organization_id}/flow")
def get_organization_flow(
    organization_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return 'Follow the Money' flow data: donors -> org -> recipient politicians.

    Each link includes the dollar weight and row count.
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org_name = org.name
    nodes = [{"id": f"org:{org_name}", "label": org_name, "type": "organization"}]
    links: list[dict] = []

    # Guard: opensecrets_id is nullable. Without it the filter
    # ``Contribution.committee_id == None`` would translate to
    # ``WHERE committee_id IS NULL`` and surface every orphan contribution
    # in the database as if it flowed from this org. Return an empty flow
    # until the org is matched to an OpenSecrets committee.
    if not org.opensecrets_id:
        return {
            "organization_id": organization_id,
            "organization_name": org_name,
            "nodes": nodes,
            "links": links,
        }

    outgoing = (
        db.query(
            Contribution.recipient_name,
            Contribution.politician_id,
            func.sum(Contribution.amount).label("weight"),
            func.count(Contribution.id).label("cnt"),
        )
        .filter(Contribution.committee_id == org.opensecrets_id)
        .group_by(Contribution.recipient_name, Contribution.politician_id)
        .order_by(func.sum(Contribution.amount).desc())
        .limit(limit)
        .all()
    )

    for row in outgoing:
        recipient = row.recipient_name or "Unknown"
        nodes.append({
            "id": f"recipient:{recipient}",
            "label": recipient,
            "type": "recipient",
        })
        links.append({
            "source": f"org:{org_name}",
            "target": f"recipient:{recipient}",
            "weight": float(row.weight or 0),
            "count": int(row.cnt or 0),
        })

    return {
        "organization_id": organization_id,
        "organization_name": org_name,
        "nodes": nodes,
        "links": links,
    }
