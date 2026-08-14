import re
import unittest
from pathlib import Path

from congress_gov_metadata_runtime import (
    congress_gov_metadata_write_mode,
    write_congress_gov_metadata,
)
from source_health import SourceHealthTracker


_REPO_ROOT = Path(__file__).resolve().parents[2]


class _Report:
    roll_calls_seen = 1
    distinct_references = 1
    references_fetched = 1
    references_not_fetched = 0
    reference_links_seen = 1
    metadata = [object()]
    roll_call_keys_by_reference = {
        "bill:119:hr:8884": ("house:119:2026:283",)
    }
    complete = True

    def rpc_payload(self):
        return (
            [{"source_record_key": "bill:119:hr:8884"}],
            [
                {
                    "measure_source_record_key": "bill:119:hr:8884",
                    "roll_call_source_record_key": "house:119:2026:283",
                }
            ],
        )


class _InvalidReport(_Report):
    def rpc_payload(self):
        raise ValueError("fact/link drift")


class _Loader:
    def __init__(self, *, configured=True):
        self.supabase = object() if configured else None
        self.calls = []

    def upsert_congress_gov_measure_metadata(self, measures, links):
        self.calls.append((measures, links))
        return {"measure_count": len(measures), "roll_call_link_count": len(links)}


class _GateOffLoader(_Loader):
    def upsert_congress_gov_measure_metadata(self, measures, links):
        self.calls.append((measures, links))
        raise RuntimeError("Congress.gov metadata production writes are disabled")


def _write_health():
    return SourceHealthTracker(
        "congress_gov_metadata_write",
        min_attempts_for_rate=1,
        max_failure_rate=0.0,
        affects_run=True,
    )


class CongressGovMetadataRuntimeTests(unittest.TestCase):
    def test_write_mode_defaults_to_disabled_and_requires_explicit_enabled(self):
        self.assertEqual("disabled", congress_gov_metadata_write_mode({}))
        self.assertEqual(
            "disabled",
            congress_gov_metadata_write_mode(
                {"CONGRESS_GOV_METADATA_WRITE_MODE": "  "}
            ),
        )
        self.assertEqual(
            "enabled",
            congress_gov_metadata_write_mode(
                {"CONGRESS_GOV_METADATA_WRITE_MODE": " ENABLED "}
            ),
        )
        for invalid in ("true", "1", "write", "typo"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                congress_gov_metadata_write_mode(
                    {"CONGRESS_GOV_METADATA_WRITE_MODE": invalid}
                )

    def test_checked_in_configuration_enables_only_reviewed_schedule(self):
        workflow = (_REPO_ROOT / ".github" / "workflows" / "scraper.yml").read_text(
            encoding="utf-8"
        )
        example_env = (_REPO_ROOT / "scraper" / "example.env").read_text(
            encoding="utf-8"
        )

        self.assertIn("congress_gov_metadata_write_mode:", workflow)
        self.assertIn("default: 'disabled'", workflow)
        expression = re.search(
            r"CONGRESS_GOV_METADATA_WRITE_MODE:\s*\$\{\{\s*(.*?)\s*\}\}",
            workflow,
        )
        self.assertIsNotNone(expression)
        self.assertEqual(
            "github.event_name == 'schedule' && 'enabled' || "
            "github.event_name == 'workflow_dispatch' "
            "&& inputs.congress_gov_metadata_write_mode || 'disabled'",
            expression.group(1),
        )
        self.assertNotIn("vars.CONGRESS_GOV_METADATA_WRITE_MODE", workflow)
        self.assertIn("CONGRESS_GOV_METADATA_WRITE_MODE=disabled", example_env)

        def resolve(event_name, manual_input, _repository_variable):
            if event_name == "schedule":
                return "enabled"
            if event_name == "workflow_dispatch":
                return manual_input or "disabled"
            return "disabled"

        self.assertEqual(
            resolve("workflow_dispatch", "disabled", "enabled"),
            "disabled",
        )
        self.assertEqual(
            resolve("workflow_dispatch", "enabled", "disabled"),
            "enabled",
        )
        self.assertEqual(resolve("schedule", None, "disabled"), "enabled")
        self.assertEqual(resolve("schedule", None, "enabled"), "enabled")
        self.assertEqual(resolve("push", None, "enabled"), "disabled")

    def test_disabled_mode_never_calls_loader(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            _Report(),
            fetch_health,
            write_health,
            mode="disabled",
            upstream_snapshots_complete=False,
            upstream_roll_call_count=1,
        )

        self.assertEqual((0, 0), result)
        self.assertEqual([], loader.calls)
        self.assertEqual("skipped", write_health.status)
        self.assertEqual(1, write_health.skip_reasons["runtime_mode_disabled"])

    def test_enabled_mode_writes_one_complete_batch(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            _Report(),
            fetch_health,
            write_health,
            mode="enabled",
            upstream_snapshots_complete=True,
            upstream_roll_call_count=1,
        )

        self.assertEqual((1, 1), result)
        self.assertEqual(1, len(loader.calls))
        self.assertEqual("healthy", write_health.status)
        self.assertEqual(1, write_health.attempts)
        self.assertEqual(1, write_health.successes)

    def test_expected_reference_skip_does_not_block_complete_exact_batch(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        fetch_health.record_skip("roll_call_reference_issue")
        self.assertEqual("degraded", fetch_health.status)
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            _Report(),
            fetch_health,
            write_health,
            mode="enabled",
            upstream_snapshots_complete=True,
            upstream_roll_call_count=1,
        )

        self.assertEqual((1, 1), result)
        self.assertEqual(1, len(loader.calls))
        self.assertEqual("healthy", write_health.status)

    def test_enabled_mode_blocks_incomplete_invalid_or_unconfigured_batch(self):
        scenarios = (
            (None, _Loader(), "metadata_snapshot_unavailable"),
            (_InvalidReport(), _Loader(), "invalid_write_payload"),
            (_Report(), _Loader(configured=False), "supabase_not_configured"),
        )
        for report, loader, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
                fetch_health.record_attempt()
                fetch_health.record_success()
                write_health = _write_health()

                result = write_congress_gov_metadata(
                    loader,
                    report,
                    fetch_health,
                    write_health,
                    mode="enabled",
                    upstream_snapshots_complete=True,
                    upstream_roll_call_count=1,
                )

                self.assertEqual((0, 0), result)
                self.assertEqual([], loader.calls)
                self.assertEqual("failed", write_health.status)
                self.assertEqual(
                    "write_preconditions_not_met",
                    write_health.breaker_reason,
                )
                self.assertEqual(1, write_health.skip_reasons[expected_reason])

    def test_source_failure_blocks_the_batch_even_when_report_claims_complete(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        fetch_health.record_attempt()
        fetch_health.record_failure("http_503")
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            _Report(),
            fetch_health,
            write_health,
            mode="enabled",
            upstream_snapshots_complete=True,
            upstream_roll_call_count=1,
        )

        self.assertEqual((0, 0), result)
        self.assertEqual([], loader.calls)
        self.assertEqual(1, write_health.skip_reasons["source_health_not_healthy"])

    def test_database_gate_failure_propagates_and_fails_blocking_tracker(self):
        loader = _GateOffLoader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        write_health = _write_health()

        with self.assertRaisesRegex(RuntimeError, "production writes are disabled"):
            write_congress_gov_metadata(
                loader,
                _Report(),
                fetch_health,
                write_health,
                mode="enabled",
                upstream_snapshots_complete=True,
                upstream_roll_call_count=1,
            )

        self.assertEqual(1, len(loader.calls))
        self.assertEqual("failed", write_health.status)
        self.assertEqual("rpc_write_failed", write_health.breaker_reason)
        self.assertEqual(1, write_health.failures)

    def test_no_supported_references_is_an_explicit_no_work_result(self):
        loader = _Loader()
        report = _Report()
        report.distinct_references = 0
        report.references_fetched = 0
        report.reference_links_seen = 0
        report.metadata = []
        report.roll_call_keys_by_reference = {}
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            report,
            SourceHealthTracker("congress_gov_metadata_shadow"),
            write_health,
            mode="enabled",
            upstream_snapshots_complete=True,
            upstream_roll_call_count=1,
        )

        self.assertEqual((0, 0), result)
        self.assertEqual([], loader.calls)
        self.assertEqual(
            1,
            write_health.skip_reasons["no_supported_measure_references"],
        )

    def test_incomplete_official_roll_call_scope_blocks_even_complete_metadata(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        write_health = _write_health()

        result = write_congress_gov_metadata(
            loader,
            _Report(),
            fetch_health,
            write_health,
            mode="enabled",
            upstream_snapshots_complete=False,
            upstream_roll_call_count=1,
        )

        self.assertEqual((0, 0), result)
        self.assertEqual([], loader.calls)
        self.assertEqual(
            1,
            write_health.skip_reasons[
                "official_roll_call_snapshots_incomplete"
            ],
        )
        self.assertEqual("failed", write_health.status)

    def test_roll_call_scope_or_fetch_counters_must_reconcile_exactly(self):
        scenarios = (
            (0, 1, 1, "roll_call_scope_mismatch"),
            (1, 0, 0, "source_health_reconciliation_mismatch"),
        )
        for expected_count, attempts, successes, expected_reason in scenarios:
            with self.subTest(expected_reason=expected_reason):
                loader = _Loader()
                fetch_health = SourceHealthTracker("congress_gov_metadata_shadow")
                for _ in range(attempts):
                    fetch_health.record_attempt()
                for _ in range(successes):
                    fetch_health.record_success()
                write_health = _write_health()

                result = write_congress_gov_metadata(
                    loader,
                    _Report(),
                    fetch_health,
                    write_health,
                    mode="enabled",
                    upstream_snapshots_complete=True,
                    upstream_roll_call_count=expected_count,
                )

                self.assertEqual((0, 0), result)
                self.assertEqual([], loader.calls)
                self.assertEqual(1, write_health.skip_reasons[expected_reason])


if __name__ == "__main__":
    unittest.main()
