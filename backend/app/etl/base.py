from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SyncResult:
    source_name: str
    started_at: datetime
    completed_at: datetime | None = None
    records_ingested: int = 0
    records_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    status: str = "running"


class BaseSourceAdapter(ABC):
    """Abstract base for all data source adapters."""

    source_name: str

    @abstractmethod
    async def fetch_records(self) -> list[dict[str, Any]]:
        """Fetch raw records from the source API or bulk file."""
        ...

    @abstractmethod
    def normalize(self, raw_record: dict[str, Any]) -> dict[str, Any]:
        """Map a raw source record to the unified data model."""
        ...

    async def run_sync(self) -> SyncResult:
        """Full ETL pipeline for this source. Opens one DB session for the batch."""
        from app.core.database import SessionLocal

        result = SyncResult(source_name=self.source_name, started_at=datetime.now(timezone.utc))
        db = SessionLocal()
        try:
            raw_records = await self.fetch_records()
            batch_size = 500
            for i, raw in enumerate(raw_records):
                try:
                    normalized = self.normalize(raw)
                    await self._upsert(normalized, db=db)
                    result.records_upserted += 1
                except Exception as e:
                    result.errors.append(str(e))
                if (i + 1) % batch_size == 0:
                    db.commit()
            db.commit()
            result.records_ingested = len(raw_records)
            result.status = "completed"
        except Exception as e:
            db.rollback()
            result.status = "failed"
            result.errors.append(f"Fatal: {e}")
        finally:
            result.completed_at = datetime.now(timezone.utc)
            db.close()
        return result

    @abstractmethod
    async def _upsert(self, record: dict[str, Any], db=None) -> None:
        """Insert or update a normalized record. Receives an open DB session."""
        ...
