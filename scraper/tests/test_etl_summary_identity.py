import io
import unittest
from contextlib import redirect_stdout

from etl_summary import ETLRunSummary
from identity import IDENTITY_SUMMARY_COUNTERS


class ETLIdentitySummaryTests(unittest.TestCase):
    def test_required_identity_counters_are_reported_when_zero(self):
        rows = ETLRunSummary().as_dict(success=True)["rows"]

        self.assertEqual(
            {key: 0 for key in IDENTITY_SUMMARY_COUNTERS},
            {key: rows[key] for key in IDENTITY_SUMMARY_COUNTERS},
        )

    def test_news_provider_summary_distinguishes_local_and_upstream_quota(self):
        summary = ETLRunSummary()
        summary.set_news_providers(
            {
                "currents": {
                    "requests": 463,
                    "requests_suppressed": 74,
                    "request_demand": 537,
                    "local_request_cap": 1000,
                    "local_requests_remaining": 537,
                    "upstream_limit": 1000,
                    "upstream_remaining": 0,
                    "upstream_reset": 1786501181,
                    "retry_after_seconds": 900,
                    "quota_exhausted": True,
                    "breaker_tripped": True,
                    "breaker_reason": "http_429",
                }
            }
        )
        output = io.StringIO()

        with redirect_stdout(output):
            summary.print(success=True)

        rendered = output.getvalue()
        self.assertIn("requests=463 suppressed=74 demand=537", rendered)
        self.assertIn("local_cap=1000 local_remaining=537", rendered)
        self.assertIn("upstream_limit=1000 upstream_remaining=0", rendered)
        self.assertIn("quota_exhausted=True", rendered)
        self.assertIn("reason=http_429", rendered)


if __name__ == "__main__":
    unittest.main()
