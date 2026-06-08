from sqlalchemy import String, Integer, Date, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date

from app.core.database import Base


class VotingRecord(Base):
    __tablename__ = "voting_record"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(Integer, ForeignKey("politician.id", ondelete="CASCADE"))
    roll_call_number: Mapped[int] = mapped_column(Integer)
    congress: Mapped[int] = mapped_column(Integer)
    session: Mapped[int] = mapped_column(Integer)
    chamber: Mapped[str] = mapped_column(String(20))
    bill_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bill_title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bill_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bill_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vote: Mapped[str] = mapped_column(String(20))
    vote_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_voting_record_dedup"),
    )
