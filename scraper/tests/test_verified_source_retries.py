import unittest
from unittest.mock import patch

import requests

from extractors import fec, openstates_votes
from source_health import SourceHealthTracker


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload if payload is not None else {"results": []}

    def json(self):
        return self._payload


class VerifiedSourceRetryTests(unittest.TestCase):
    def tearDown(self):
        fec.reset_budget()
        openstates_votes.reset_budget()

    @patch("extractors.fec.time.sleep")
    @patch("extractors.fec.requests.get")
    def test_fec_timeout_retries_once_and_records_logical_success(
        self, mock_get, mock_sleep
    ):
        mock_get.side_effect = [requests.Timeout("slow"), FakeResponse()]
        health = SourceHealthTracker("openfec")

        payload = fec._get("/candidate/example/committees/", {}, health=health)

        self.assertEqual({"results": []}, payload)
        self.assertEqual(2, mock_get.call_count)
        mock_sleep.assert_called_once_with(fec._RETRY_BACKOFF_SECONDS)
        self.assertEqual(2, fec._request_count)
        self.assertEqual(1, health.attempts)
        self.assertEqual(1, health.successes)
        self.assertEqual(0, health.failures)

    @patch("extractors.fec.time.sleep")
    @patch("extractors.fec.requests.get")
    def test_fec_503_retries_once(self, mock_get, mock_sleep):
        mock_get.side_effect = [FakeResponse(status_code=503), FakeResponse()]
        health = SourceHealthTracker("openfec")

        payload = fec._get("/candidate/example/committees/", {}, health=health)

        self.assertEqual({"results": []}, payload)
        self.assertEqual(2, mock_get.call_count)
        mock_sleep.assert_called_once_with(fec._RETRY_BACKOFF_SECONDS)
        self.assertEqual(1, health.attempts)
        self.assertEqual(1, health.successes)
        self.assertEqual(0, health.failures)

    @patch("extractors.fec.time.sleep")
    @patch("extractors.fec.requests.get")
    def test_fec_exhausted_retry_records_one_logical_failure(
        self, mock_get, _mock_sleep
    ):
        mock_get.side_effect = [requests.Timeout("slow"), requests.Timeout("still slow")]
        health = SourceHealthTracker("openfec")

        payload = fec._get("/schedules/schedule_a/", {}, health=health)

        self.assertIsNone(payload)
        self.assertEqual(2, mock_get.call_count)
        self.assertEqual(2, fec._request_count)
        self.assertEqual(1, health.attempts)
        self.assertEqual(0, health.successes)
        self.assertEqual(1, health.failures)
        self.assertEqual(1, health.failure_reasons["timeout"])

    @patch("extractors.openstates_votes.time.sleep")
    @patch("extractors.openstates_votes.requests.get")
    def test_openstates_timeout_retries_once_and_records_logical_success(
        self, mock_get, mock_sleep
    ):
        mock_get.side_effect = [requests.Timeout("slow"), FakeResponse()]
        health = SourceHealthTracker("openstates_votes")

        payload = openstates_votes._get("/bills", {}, "key", health=health)

        self.assertEqual({"results": []}, payload)
        self.assertEqual(2, mock_get.call_count)
        self.assertTrue(
            any(
                call.args == (openstates_votes._RETRY_BACKOFF_SECONDS,)
                for call in mock_sleep.call_args_list
            )
        )
        self.assertEqual(2, openstates_votes._request_count)
        self.assertEqual(1, health.attempts)
        self.assertEqual(1, health.successes)
        self.assertEqual(0, health.failures)

    @patch("extractors.openstates_votes.time.sleep")
    @patch("extractors.openstates_votes.requests.get")
    def test_openstates_rate_limit_does_not_retry_and_opens_breaker(
        self, mock_get, mock_sleep
    ):
        mock_get.return_value = FakeResponse(status_code=429)
        health = SourceHealthTracker("openstates_votes")

        payload = openstates_votes._get("/bills", {}, "key", health=health)

        self.assertIsNone(payload)
        self.assertEqual(1, mock_get.call_count)
        mock_sleep.assert_not_called()
        self.assertEqual(1, openstates_votes._request_count)
        self.assertEqual(1, health.failures)
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("http_429", health.breaker_reason)


if __name__ == "__main__":
    unittest.main()
