import json
from collections import Counter
from datetime import datetime, timezone


class ETLRunSummary:
    def __init__(self):
        self.started_at = datetime.now(timezone.utc)
        self.finished_at = None
        self.counters = Counter()
        self.skips = Counter()
        self.errors = []
        self.schema_preflight = {"status": "not_run"}
        self.identity_health = {"status": "not_run"}
        self.news_providers = {}

    def increment(self, key: str, amount: int = 1) -> None:
        if amount:
            self.counters[key] += amount

    def skip(self, source: str, reason: str) -> None:
        self.skips[f"{source}: {reason}"] += 1

    def error(self, scope: str, message: str) -> None:
        self.errors.append({"scope": scope, "message": str(message)})

    def set_schema_preflight(self, status: str, details: list[str] | None = None) -> None:
        payload = {"status": status}
        if details:
            payload["details"] = details
        self.schema_preflight = payload

    def set_identity_health(
        self,
        status: str,
        checks: dict | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        payload = {"status": status}
        if checks is not None:
            payload["checks"] = checks
        if warnings:
            payload["warnings"] = warnings
        self.identity_health = payload

    def set_news_providers(self, status: dict) -> None:
        self.news_providers = status

    def as_dict(self, success: bool) -> dict:
        finished = self.finished_at or datetime.now(timezone.utc)
        duration = (finished - self.started_at).total_seconds()
        return {
            "success": success,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": round(duration, 2),
            "schema_preflight": self.schema_preflight,
            "identity_health": self.identity_health,
            "rows": dict(sorted(self.counters.items())),
            "source_skips": dict(sorted(self.skips.items())),
            "errors": self.errors,
            "news_providers": self.news_providers,
        }

    def print(self, success: bool) -> None:
        self.finished_at = datetime.now(timezone.utc)
        payload = self.as_dict(success)

        print("\n=== ETL Run Summary ===")
        print(f"success: {payload['success']}")
        print(f"duration_seconds: {payload['duration_seconds']}")
        print(f"schema_preflight: {payload['schema_preflight'].get('status')}")
        print(f"identity_health: {payload['identity_health'].get('status')}")
        identity_checks = payload["identity_health"].get("checks") or {}
        for key, value in sorted(identity_checks.items()):
            print(f"  {key}: {value}")
        identity_warnings = payload["identity_health"].get("warnings") or []
        if identity_warnings:
            print("identity_health_warnings:")
            for warning in identity_warnings:
                print(f"  {warning}")

        print("rows:")
        if payload["rows"]:
            for key, value in payload["rows"].items():
                print(f"  {key}: {value}")
        else:
            print("  none")

        print("source_skips:")
        if payload["source_skips"]:
            for key, value in payload["source_skips"].items():
                print(f"  {key}: {value}")
        else:
            print("  none")

        print("news_providers:")
        if payload["news_providers"]:
            for provider, status in payload["news_providers"].items():
                print(
                    f"  {provider}: requests={status.get('requests')} "
                    f"limit={status.get('limit')} breaker_tripped={status.get('breaker_tripped')}"
                )
        else:
            print("  none")

        if payload["errors"]:
            print("errors:")
            for item in payload["errors"]:
                print(f"  {item['scope']}: {item['message']}")
        else:
            print("errors: none")

        print("ETL_SUMMARY_JSON=" + json.dumps(payload, sort_keys=True))
