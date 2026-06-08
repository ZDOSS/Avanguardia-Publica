from sqlalchemy import Integer, Float, String, ARRAY, UniqueConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PoliticianContribution(Base):
    __tablename__ = "politician_contribution"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(ForeignKey("politician.id"))
    contribution_id: Mapped[int] = mapped_column(ForeignKey("contribution.id"))
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_method: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    __table_args__ = (
        UniqueConstraint("politician_id", "contribution_id", name="uq_politician_contribution"),
    )


class PoliticianLobbyingRecord(Base):
    __tablename__ = "politician_lobbying_record"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(ForeignKey("politician.id"))
    lobbying_record_id: Mapped[int] = mapped_column(ForeignKey("lobbying_record.id"))
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_method: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    __table_args__ = (
        UniqueConstraint("politician_id", "lobbying_record_id", name="uq_politician_lobbying"),
    )


class PoliticianGovernmentContract(Base):
    __tablename__ = "politician_government_contract"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(ForeignKey("politician.id"))
    contract_id: Mapped[int] = mapped_column(ForeignKey("government_contract.id"))
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_method: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)

    __table_args__ = (
        UniqueConstraint("politician_id", "contract_id", name="uq_politician_contract"),
    )
