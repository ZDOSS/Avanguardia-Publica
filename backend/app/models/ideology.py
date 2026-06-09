from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PoliticianIdeologyScore(Base):
    __tablename__ = "politician_ideology_score"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    politician_id: Mapped[int] = mapped_column(Integer, ForeignKey("politician.id", ondelete="CASCADE"))
    congress: Mapped[int] = mapped_column(Integer)
    chamber: Mapped[str] = mapped_column(String(20))
    dw_nominate_dim1: Mapped[float | None] = mapped_column(Float, nullable=True)
    dw_nominate_dim2: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(50))
    source_record_id: Mapped[str] = mapped_column(String(100))

    __table_args__ = (
        UniqueConstraint("source_name", "source_record_id", name="uq_ideology_score_dedup"),
    )
