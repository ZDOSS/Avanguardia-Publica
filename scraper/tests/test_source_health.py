import unittest

from etl_summary import ETLRunSummary
from source_health import SourceHealthTracker


class SourceHealthTests(unittest.TestCase):
    def test_single_transient_failure_is_degraded_not_blocking(self):
        tracker = SourceHealthTracker("govtrack", min_attempts_for_rate=10)
        tracker.record_attempt()
        tracker.record_failure("timeout", 1.5)

        self.assertEqual("degraded", tracker.status)
        self.assertFalse(tracker.breaker_tripped)
        self.assertEqual(1, tracker.snapshot()["failure_reasons"]["timeout"])

    def test_repeated_failure_rate_crosses_blocking_threshold(self):
        summary = ETLRunSummary()
        tracker = summary.source_tracker(
            "openfec", min_attempts_for_rate=4, max_failure_rate=0.5
        )
        for _ in range(4):
            tracker.record_attempt()
        tracker.record_success()
        tracker.record_failure("timeout")
        tracker.record_failure("timeout")
        tracker.record_failure("http_502")

        self.assertEqual("failed", tracker.status)
        self.assertEqual(["openfec"], summary.run_blocking_source_failures())

    def test_openfec_budget_tolerates_observed_scattered_timeouts(self):
        tracker = SourceHealthTracker(
            "openfec", min_attempts_for_rate=10, max_failure_seconds=600
        )
        for _ in range(55):
            tracker.record_attempt()
            tracker.record_success()
        for _ in range(10):
            tracker.record_attempt()
            tracker.record_failure("timeout", 31.749)

        self.assertEqual("degraded", tracker.status)
        self.assertFalse(tracker.breaker_tripped)
        self.assertAlmostEqual(10 / 65, tracker.failure_rate)
        self.assertGreater(tracker.failure_seconds, 300)
        self.assertLess(tracker.failure_seconds, 600)

    def test_openfec_larger_time_budget_still_blocks_high_failure_rate(self):
        tracker = SourceHealthTracker(
            "openfec", min_attempts_for_rate=10, max_failure_seconds=600
        )
        for _ in range(7):
            tracker.record_attempt()
            tracker.record_success()
        for _ in range(3):
            tracker.record_attempt()
            tracker.record_failure("timeout", 1)

        self.assertEqual("failed", tracker.status)
        self.assertEqual("failure_rate_threshold_exceeded", tracker.breaker_reason)

    def test_openstates_votes_tolerate_small_sample_exhausted_retries(self):
        tracker = SourceHealthTracker(
            "openstates_votes", min_attempts_for_rate=10, max_failure_seconds=300
        )
        for _ in range(3):
            tracker.record_attempt()
            tracker.record_success()
        for _ in range(2):
            tracker.record_attempt()
            tracker.record_failure("timeout", 60.635)

        self.assertEqual("degraded", tracker.status)
        self.assertFalse(tracker.breaker_tripped)
        self.assertAlmostEqual(2 / 5, tracker.failure_rate)
        self.assertGreater(tracker.failure_seconds, 120)
        self.assertLess(tracker.failure_seconds, 300)

    def test_openstates_votes_still_block_high_failure_rate_after_sample(self):
        tracker = SourceHealthTracker(
            "openstates_votes", min_attempts_for_rate=10, max_failure_seconds=300
        )
        for _ in range(7):
            tracker.record_attempt()
            tracker.record_success()
        for _ in range(3):
            tracker.record_attempt()
            tracker.record_failure("timeout", 1)

        self.assertEqual("failed", tracker.status)
        self.assertEqual("failure_rate_threshold_exceeded", tracker.breaker_reason)

    def test_expected_request_budget_exhaustion_is_visible_but_not_failed(self):
        tracker = SourceHealthTracker("openstates_votes")
        tracker.record_attempt()
        tracker.record_success()
        tracker.record_skip("request_budget_exhausted", 20)

        snapshot = tracker.snapshot()
        self.assertEqual("degraded", snapshot["status"])
        self.assertFalse(snapshot["breaker_tripped"])
        self.assertEqual(20, snapshot["skip_reasons"]["request_budget_exhausted"])

    def test_failed_unverified_enrichment_is_visible_but_does_not_block_run(self):
        summary = ETLRunSummary()
        tracker = summary.source_tracker(
            "littlesis",
            min_attempts_for_rate=1,
            max_failure_rate=0.5,
            affects_run=False,
        )
        tracker.record_attempt()
        tracker.record_failure("http_503")

        self.assertEqual("failed", tracker.status)
        self.assertEqual([], summary.run_blocking_source_failures())
        payload = summary.as_dict(success=True)
        self.assertEqual("failed", payload["source_health"]["littlesis"]["status"])
        self.assertEqual([], payload["source_health_blocking_failures"])


if __name__ == "__main__":
    unittest.main()
