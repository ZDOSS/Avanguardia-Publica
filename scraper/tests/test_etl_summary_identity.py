import unittest

from etl_summary import ETLRunSummary
from identity import IDENTITY_SUMMARY_COUNTERS


class ETLIdentitySummaryTests(unittest.TestCase):
    def test_required_identity_counters_are_reported_when_zero(self):
        rows = ETLRunSummary().as_dict(success=True)["rows"]

        self.assertEqual(
            {key: 0 for key in IDENTITY_SUMMARY_COUNTERS},
            {key: rows[key] for key in IDENTITY_SUMMARY_COUNTERS},
        )


if __name__ == "__main__":
    unittest.main()
