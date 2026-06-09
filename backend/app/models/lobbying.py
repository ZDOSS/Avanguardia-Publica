from sqlalchemy import Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LobbyingRecord(Base):
    __tablename__ = "lobbying_record"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lda_id: Mapped[str] = mapped_column(String(50))
    registrant_name: Mapped[str] = mapped_column(String(500))
    client_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lobbyist_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    issue_area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    report_quarter: Mapped[str | None] = mapped_column(String(10), nullable=True)
    filing_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    government_entities_lobbied: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_xml_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_lobbying_dedup"),
    )
