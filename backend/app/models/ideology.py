from sqlalchemy import String, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PoliticianIdeologyScore(Base):
    __tablename__ = "politician_ideology_score"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(Integer)
    congress: Mapped[int] = mapped_column(Integer)
    chamber: Mapped[str] = mapped_column(String(20))
    dw_nominate_dim1: Mapped[float | None] = mapped_column(nullable=True)
    dw_nominate_dim2: Mapped[float | None] = mapped_column(nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        UniqueConstraint("politician_id", "congress", "chamber", name="uq_ideology_score"),
    )
