from sqlalchemy import String, Float, Integer, UniqueConstraint, Date, Text
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date

from app.core.database import Base


class FinancialDisclosure(Base):
    __tablename__ = "financial_disclosure"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(Integer)
    filing_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filing_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    asset_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount_range_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    notification_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_financial_dedup"),
    )
