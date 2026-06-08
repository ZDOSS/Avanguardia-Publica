from sqlalchemy import String, Float, Integer, UniqueConstraint, Date, Text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date

from app.core.database import Base


class GovernmentContract(Base):
    __tablename__ = "government_contract"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    award_id: Mapped[str] = mapped_column(String(100))
    recipient_name: Mapped[str] = mapped_column(String(500))
    awarding_agency: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    award_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    naics_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    place_of_performance: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_contract_dedup"),
    )
