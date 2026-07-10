from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class SourceHealthTracker:
    """Small in-memory health ledger for one ETL source.

    A single transient failure makes a source ``degraded`` but does not stop the run.
    Repeated failures, excessive time lost to failures, or an explicit circuit breaker
    make it ``failed``.  ``affects_run`` lets a provider-level fallback fail without
    failing the aggregate pipeline when another provider still serves the data.
    """

    source: str
    max_failure_rate: float = 0.25
    min_attempts_for_rate: int = 10
    max_failure_seconds: float = 120.0
    affects_run: bool = True
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    skips: int = 0
    request_seconds: float = 0.0
    failure_seconds: float = 0.0
    breaker_tripped: bool = False
    breaker_reason: str | None = None
    failure_reasons: Counter = field(default_factory=Counter)
    skip_reasons: Counter = field(default_factory=Counter)

    def record_attempt(self) -> None:
        self.attempts += 1

    def record_success(self, elapsed_seconds: float = 0.0) -> None:
        self.successes += 1
        self.request_seconds += max(0.0, float(elapsed_seconds or 0.0))

    def record_failure(self, reason: str, elapsed_seconds: float = 0.0) -> None:
        elapsed = max(0.0, float(elapsed_seconds or 0.0))
        self.failures += 1
        self.request_seconds += elapsed
        self.failure_seconds += elapsed
        self.failure_reasons[reason or "unknown"] += 1

        threshold_reason = self.threshold_reason()
        if threshold_reason:
            self.trip_breaker(threshold_reason)

    def record_skip(self, reason: str, count: int = 1) -> None:
        if count <= 0:
            return
        self.skips += count
        self.skip_reasons[reason or "unspecified"] += count

    def trip_breaker(self, reason: str) -> None:
        self.breaker_tripped = True
        if not self.breaker_reason:
            self.breaker_reason = reason or "circuit_breaker"

    @property
    def failure_rate(self) -> float:
        return self.failures / self.attempts if self.attempts else 0.0

    def threshold_reason(self) -> str | None:
        if self.max_failure_seconds > 0 and self.failure_seconds >= self.max_failure_seconds:
            return "failure_time_budget_exhausted"
        if (
            self.attempts >= self.min_attempts_for_rate
            and self.failure_rate >= self.max_failure_rate
        ):
            return "failure_rate_threshold_exceeded"
        return None

    @property
    def status(self) -> str:
        if self.breaker_tripped or self.threshold_reason():
            return "failed"
        if self.failures or (self.skips and self.attempts):
            return "degraded"
        if not self.attempts and self.skips:
            return "skipped"
        if not self.attempts:
            return "not_run"
        return "healthy"

    def snapshot(self) -> dict:
        degraded_reason = self.breaker_reason
        if not degraded_reason and self.failures:
            degraded_reason = "transient_failures"
        elif not degraded_reason and self.skips and self.attempts:
            degraded_reason = "partial_skips"

        return {
            "status": self.status,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "skips": self.skips,
            "failure_rate": round(self.failure_rate, 4),
            "request_seconds": round(self.request_seconds, 2),
            "failure_seconds": round(self.failure_seconds, 2),
            "breaker_tripped": self.breaker_tripped,
            "degraded_reason": degraded_reason,
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
            "skip_reasons": dict(sorted(self.skip_reasons.items())),
            "affects_run": self.affects_run,
        }
