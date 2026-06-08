from sqlalchemy import String, Integer, Float, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    last_synced_at: Mapped[str | None] = mapped_column(nullable=True)
    sync_interval: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    config: Mapped[dict | None] = mapped_column(nullable=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(nullable=True)
