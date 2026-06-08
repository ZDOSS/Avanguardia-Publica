from sqlalchemy import String, Boolean, DateTime, JSON, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.core.database import Base


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500))
    type: Mapped[str] = mapped_column(String(50))
    fec_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opensecrets_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_organization_dedup"),
    )
