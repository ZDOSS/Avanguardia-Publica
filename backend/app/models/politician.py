from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Politician(Base):
    __tablename__ = "politician"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    first_name: Mapped[str] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str] = mapped_column(String(100))
    suffix: Mapped[str | None] = mapped_column(String(20), nullable=True)
    full_name: Mapped[str] = mapped_column(String(300))
    party_history: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(2))
    district: Mapped[str | None] = mapped_column(String(10), nullable=True)
    chamber: Mapped[str] = mapped_column(String(20))
    bioguide_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fec_ids: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    lis_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    icpsr_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    voteview_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    govtrack_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opensecrets_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bio_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    in_office: Mapped[bool] = mapped_column(Boolean, default=True)
    term_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    term_end: Mapped[list | None] = mapped_column(ARRAY(DateTime(timezone=True)), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
    last_data_refresh: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    search_tsv: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_politician_dedup"),
    )
