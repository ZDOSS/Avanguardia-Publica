from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Contribution(Base):
    __tablename__ = "contribution"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    donor_name: Mapped[str] = mapped_column(String(300))
    donor_type: Mapped[str] = mapped_column(String(50))
    recipient_name: Mapped[str] = mapped_column(String(300))
    committee_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    politician_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("politician.id", ondelete="CASCADE"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    election_cycle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fec_filing_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amendment_indicator: Mapped[str | None] = mapped_column(String(5), nullable=True)
    employer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    occupation: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))
    search_tsv: Mapped[Any | None] = mapped_column(TSVECTOR, nullable=True)

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_contribution_dedup"),
    )
