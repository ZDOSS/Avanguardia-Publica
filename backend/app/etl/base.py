from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
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
        """Full ETL pipeline for this source."""
        result = SyncResult(source_name=self.source_name, started_at=datetime.utcnow())
        try:
            raw_records = await self.fetch_records()
            for raw in raw_records:
                try:
                    normalized = self.normalize(raw)
                    await self._upsert(normalized)
                    result.records_upserted += 1
                except Exception as e:
                    result.errors.append(str(e))
            result.records_ingested = len(raw_records)
            result.status = "completed"
        except Exception as e:
            result.status = "failed"
            result.errors.append(f"Fatal: {e}")
        finally:
            result.completed_at = datetime.utcnow()
        return result

    @abstractmethod
    async def _upsert(self, record: dict[str, Any]) -> None:
        """Insert or update a normalized record in the database."""
        ...
