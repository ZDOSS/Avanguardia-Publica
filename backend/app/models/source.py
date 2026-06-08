from sqlalchemy import String, Integer, JSON, ARRAY, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from app.core.database import Base


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_interval: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
