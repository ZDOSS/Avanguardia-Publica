import re
import unittest
from pathlib import Path

from extractors.senate_roll_calls import (
    SenateMemberVote,
    SenateRollCall,
    SenateRollCallShadowReport,
)
from senate_roll_call_runtime import (
    senate_roll_call_write_mode,
    write_senate_roll_calls,
)
from source_health import SourceHealthTracker


_REPO_ROOT = Path(__file__).resolve().parents[2]


class _Loader:
    def __init__(self):
        self.supabase = object()
        self.calls = []

    def upsert_senate_roll_call(self, roll_call, member_votes):
        self.calls.append((roll_call, member_votes))
        return {
            "roll_call_source_record_id": "roll-call-source-id",
            "member_vote_count": len(member_votes),
        }


class _GateOffLoader(_Loader):
    def upsert_senate_roll_call(self, roll_call, member_votes):
        self.calls.append((roll_call, member_votes))
        raise RuntimeError("Senate production writes are disabled")


class _BrokenReport:
    snapshot_complete = False
    roll_calls = []

    def authoritative_write_block_reasons(self, _fetch_health):
        raise RuntimeError("eligibility check failed")


def _eligible_report() -> SenateRollCallShadowReport:
    roll_call = SenateRollCall(
        congress=119,
        session=2,
        congress_year=2026,
        vote_number=2,
        vote_date="2026-07-14",
        question="On Passage",
        source_url=(
            "https://www.senate.gov/legislative/LIS/roll_call_votes/"
            "vote1192/vote_119_2_00002.xml"
        ),
        member_votes=(
            SenateMemberVote("S001", "Yea", "A000001"),
            SenateMemberVote("S002", "Nay", "B000002"),
        ),
        vote_result="Passed",
        payload_hash="a" * 64,
        fetched_at="2026-07-21T12:00:00+00:00",
        official_member_vote_total=2,
    )
    return SenateRollCallShadowReport(
        roll_calls_listed=1,
        roll_calls_fetched=1,
        member_votes_seen=2,
        exact_lis_matches=2,
        govtrack_roll_calls_reconciled=1,
        govtrack_vote_cast_matches=2,
        listing_complete=True,
        roll_calls=[roll_call],
    )


class SenateRollCallRuntimeTests(unittest.TestCase):
    def test_write_mode_defaults_to_disabled(self):
        self.assertEqual("disabled", senate_roll_call_write_mode({}))
        self.assertEqual(
            "disabled",
            senate_roll_call_write_mode({"SENATE_ROLL_CALL_WRITE_MODE": "  "}),
        )

    def test_write_mode_accepts_only_explicit_enabled_value(self):
        self.assertEqual(
            "enabled",
            senate_roll_call_write_mode(
                {"SENATE_ROLL_CALL_WRITE_MODE": " ENABLED "}
            ),
        )
        for invalid in ("true", "1", "write", "typo"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                senate_roll_call_write_mode(
                    {"SENATE_ROLL_CALL_WRITE_MODE": invalid}
                )

    def test_checked_in_runtime_configuration_requires_manual_opt_in(self):
        workflow = (_REPO_ROOT / ".github" / "workflows" / "scraper.yml").read_text(
            encoding="utf-8"
        )
        example_env = (_REPO_ROOT / "scraper" / "example.env").read_text(
            encoding="utf-8"
        )

        self.assertIn("senate_roll_call_write_mode:", workflow)
        self.assertIn("type: choice", workflow)
        self.assertIn("default: 'disabled'", workflow)
        expression = re.search(
            r"SENATE_ROLL_CALL_WRITE_MODE:\s*\$\{\{\s*(.*?)\s*\}\}",
            workflow,
        )
        self.assertIsNotNone(expression)
        self.assertEqual(
            expression.group(1),
            "github.event_name == 'workflow_dispatch' "
            "&& inputs.senate_roll_call_write_mode || 'disabled'",
        )
        self.assertNotIn("vars.SENATE_ROLL_CALL_WRITE_MODE", workflow)
        self.assertIn("SENATE_ROLL_CALL_WRITE_MODE=disabled", example_env)

        def resolve(event_name, manual_input, _repository_variable):
            if event_name == "workflow_dispatch":
                return manual_input or "disabled"
            return "disabled"

        self.assertEqual(resolve("workflow_dispatch", "disabled", "enabled"), "disabled")
        self.assertEqual(resolve("workflow_dispatch", "enabled", "disabled"), "enabled")
        self.assertEqual(resolve("schedule", None, "disabled"), "disabled")
        self.assertEqual(resolve("schedule", None, "enabled"), "disabled")
        self.assertEqual(resolve("push", None, "enabled"), "disabled")

    def test_disabled_mode_never_calls_the_loader(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        write_health = SourceHealthTracker(
            "senate_roll_call_write", min_attempts_for_rate=1
        )

        written = write_senate_roll_calls(
            loader,
            SenateRollCallShadowReport(),
            fetch_health,
            write_health,
            mode="disabled",
        )

        self.assertEqual(0, written)
        self.assertEqual([], loader.calls)
        self.assertEqual("skipped", write_health.status)
        self.assertEqual(1, write_health.skip_reasons["runtime_mode_disabled"])

    def test_enabled_mode_blocks_the_entire_incomplete_snapshot(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        fetch_health.record_attempt()
        fetch_health.record_failure("http_500")
        write_health = SourceHealthTracker(
            "senate_roll_call_write", min_attempts_for_rate=1
        )
        report = SenateRollCallShadowReport(
            roll_calls_listed=2,
            roll_calls_fetched=1,
            listing_complete=True,
        )

        written = write_senate_roll_calls(
            loader,
            report,
            fetch_health,
            write_health,
            mode="enabled",
        )

        self.assertEqual(0, written)
        self.assertEqual([], loader.calls)
        self.assertEqual("failed", write_health.status)
        self.assertEqual("write_preconditions_not_met", write_health.breaker_reason)
        self.assertEqual(1, write_health.skip_reasons["incomplete_snapshot"])
        self.assertEqual(1, write_health.skip_reasons["source_health_not_healthy"])

    def test_enabled_mode_writes_each_eligible_roll_call_once(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        for _ in range(2):
            fetch_health.record_attempt()
            fetch_health.record_success()
        write_health = SourceHealthTracker(
            "senate_roll_call_write",
            min_attempts_for_rate=1,
            max_failure_rate=0.0,
            affects_run=True,
        )

        written = write_senate_roll_calls(
            loader,
            _eligible_report(),
            fetch_health,
            write_health,
            mode="enabled",
        )

        self.assertEqual(1, written)
        self.assertEqual(1, len(loader.calls))
        roll_call_payload, member_votes = loader.calls[0]
        self.assertEqual("senate:119:2026:2", roll_call_payload["source_record_key"])
        self.assertEqual(
            ["senate:119:2026:2:S001", "senate:119:2026:2:S002"],
            [member_vote["source_record_key"] for member_vote in member_votes],
        )
        self.assertEqual("healthy", write_health.status)
        self.assertEqual(1, write_health.attempts)
        self.assertEqual(1, write_health.successes)

    def test_database_gate_failure_marks_the_enabled_runtime_source_failed(self):
        loader = _GateOffLoader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        for _ in range(2):
            fetch_health.record_attempt()
            fetch_health.record_success()
        write_health = SourceHealthTracker(
            "senate_roll_call_write", min_attempts_for_rate=1
        )

        with self.assertRaisesRegex(RuntimeError, "production writes are disabled"):
            write_senate_roll_calls(
                loader,
                _eligible_report(),
                fetch_health,
                write_health,
                mode="enabled",
            )

        self.assertEqual(1, len(loader.calls))
        self.assertEqual("failed", write_health.status)
        self.assertEqual("rpc_write_failed", write_health.breaker_reason)
        self.assertEqual(1, write_health.failures)

    def test_unexpected_eligibility_error_fails_the_enabled_write_source(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        write_health = SourceHealthTracker(
            "senate_roll_call_write", min_attempts_for_rate=1
        )

        with self.assertRaisesRegex(RuntimeError, "eligibility check failed"):
            write_senate_roll_calls(
                loader,
                _BrokenReport(),
                fetch_health,
                write_health,
                mode="enabled",
            )

        self.assertEqual("failed", write_health.status)
        self.assertEqual("unexpected_write_error", write_health.breaker_reason)
        self.assertEqual(1, write_health.failures)

    def test_enabled_mode_treats_a_complete_empty_listing_as_no_work(self):
        loader = _Loader()
        fetch_health = SourceHealthTracker("senate_roll_call_shadow")
        fetch_health.record_attempt()
        fetch_health.record_success()
        fetch_health.record_skip("no_current_session_roll_calls")
        write_health = SourceHealthTracker(
            "senate_roll_call_write", min_attempts_for_rate=1
        )

        written = write_senate_roll_calls(
            loader,
            SenateRollCallShadowReport(listing_complete=True),
            fetch_health,
            write_health,
            mode="enabled",
        )

        self.assertEqual(0, written)
        self.assertEqual([], loader.calls)
        self.assertEqual("skipped", write_health.status)
        self.assertEqual(1, write_health.skip_reasons["no_current_session_roll_calls"])


if __name__ == "__main__":
    unittest.main()
