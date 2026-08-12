import io
import os
import unittest
import zipfile
from unittest.mock import patch

from extractors import news_aggregator


class _Response:
    def __init__(
        self,
        *,
        payload=None,
        status_code=200,
        headers=None,
        text="",
        content=b"",
    ):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = content

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return self._payload if self._payload is not None else {
            "news": [
                {
                    "title": "A verified headline",
                    "description": "This description must not be persisted.",
                    "url": "https://publisher.test/story",
                    "author": "Publisher",
                }
            ]
        }

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class NewsUsagePolicyTests(unittest.TestCase):
    def setUp(self):
        news_aggregator.reset_provider_status()
        news_aggregator._gdelt_cache = None
        news_aggregator._gdelt_cache_url = None
        news_aggregator._gdelt_cache_time = None

    def test_provider_response_keeps_headline_link_and_provenance_only(self):
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get", return_value=_Response()
        ):
            rows = news_aggregator._fetch_currents("Alex Public")

        self.assertEqual("A verified headline", rows[0]["content_summary"])
        self.assertNotIn("description", rows[0])
        self.assertEqual("Currents", rows[0]["source_api"])
        self.assertEqual("https://publisher.test/story", rows[0]["url"])

    def test_provider_status_separates_attempts_local_cap_and_upstream_quota(self):
        response = _Response(
            headers={
                "X-RateLimit-Limit": "1000",
                "X-RateLimit-Remaining": "998",
                "X-RateLimit-Reset": "1786501181",
                "Retry-After": "900",
                "Authorization": "must-not-be-retained",
            }
        )
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get", return_value=response
        ):
            news_aggregator._fetch_currents("Alex Public")

        status = news_aggregator.get_provider_status()["currents"]
        self.assertEqual(1, status["requests"])
        self.assertEqual(0, status["requests_suppressed"])
        self.assertEqual(1, status["request_demand"])
        self.assertEqual(1000, status["local_request_cap"])
        self.assertEqual(999, status["local_requests_remaining"])
        self.assertEqual(1000, status["upstream_limit"])
        self.assertEqual(998, status["upstream_remaining"])
        self.assertEqual(1786501181, status["upstream_reset"])
        self.assertEqual(900, status["retry_after_seconds"])
        self.assertFalse(status["breaker_tripped"])
        self.assertNotIn("must-not-be-retained", repr(status))

    def test_http_429_does_not_fake_local_cap_saturation(self):
        response = _Response(
            status_code=429,
            headers={"X-RateLimit-Remaining": "0", "Retry-After": "900"},
        )
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get", return_value=response
        ) as request:
            news_aggregator._fetch_currents("Alex Public")
            news_aggregator._fetch_currents("Jordan Public")

        status = news_aggregator.get_provider_status()["currents"]
        self.assertEqual(1, request.call_count)
        self.assertEqual(1, status["requests"])
        self.assertEqual(1, status["requests_suppressed"])
        self.assertEqual(2, status["request_demand"])
        self.assertEqual(999, status["local_requests_remaining"])
        self.assertEqual("http_429", status["breaker_reason"])
        self.assertTrue(status["breaker_tripped"])
        self.assertTrue(status["quota_exhausted"])

    def test_transport_timeout_counts_the_attempt_and_records_its_cause(self):
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get",
            side_effect=news_aggregator.requests.Timeout("timed out"),
        ):
            news_aggregator._fetch_currents("Alex Public")

        status = news_aggregator.get_provider_status()["currents"]
        self.assertEqual(1, status["requests"])
        self.assertEqual("timeout", status["breaker_reason"])
        self.assertTrue(status["breaker_tripped"])
        self.assertFalse(status["quota_exhausted"])

    def test_zero_upstream_remaining_stops_before_an_extra_request(self):
        response = _Response(headers={"X-RateLimit-Remaining": "0"})
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get", return_value=response
        ) as request:
            news_aggregator._fetch_currents("Alex Public")
            news_aggregator._fetch_currents("Jordan Public")

        status = news_aggregator.get_provider_status()["currents"]
        self.assertEqual(1, request.call_count)
        self.assertEqual(1, status["requests_suppressed"])
        self.assertEqual(2, status["request_demand"])
        self.assertEqual("upstream_quota_exhausted", status["breaker_reason"])
        self.assertTrue(status["quota_exhausted"])

    def test_last_successful_response_is_not_discarded_when_quota_reaches_zero(self):
        response = _Response(headers={"X-RateLimit-Remaining": "0"})
        environment = {"APP_ENV": "production", "CURRENTS_API_KEY": "test"}
        with patch.dict(os.environ, environment, clear=True), patch(
            "extractors.news_aggregator.requests.get", return_value=response
        ) as request, patch(
            "extractors.news_aggregator._fetch_gdelt"
        ) as gdelt:
            rows = news_aggregator.get_news_data("Alex Public")

        self.assertEqual("A verified headline", rows[0]["content_summary"])
        self.assertEqual(1, request.call_count)
        gdelt.assert_not_called()

    def test_gdelt_is_url_discovery_only_with_attribution(self):
        with patch(
            "extractors.news_aggregator._fetch_gdelt_urls",
            return_value=["https://publisher.test/gdelt-story"],
        ):
            rows = news_aggregator._fetch_gdelt("Alex Public")

        self.assertEqual("GDELT", rows[0]["source_api"])
        self.assertIn("GDELT Project", rows[0]["content_summary"])
        self.assertEqual("gdelt_gkg_url_discovery", rows[0]["ingestion_method"])

    def test_gdelt_uses_certificate_valid_storage_urls(self):
        archive = io.BytesIO()
        columns = [str(index) for index in range(12)]
        columns[4] = "https://publisher.test/gdelt-story"
        columns[11] = "Alex Public;Jordan Public"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("20260812001500.gkg.csv", "\t".join(columns) + "\n")

        source_url = (
            "http://data.gdeltproject.org/"
            "gdeltv2/20260812001500.gkg.csv.zip"
        )
        manifest = f"123 hash {source_url}\n"
        with patch(
            "extractors.news_aggregator.requests.get",
            side_effect=[
                _Response(text=manifest),
                _Response(content=archive.getvalue()),
            ],
        ) as request:
            cache = news_aggregator._get_gdelt_cache()

        self.assertEqual(
            [("https://publisher.test/gdelt-story", "alex public;jordan public")],
            cache,
        )
        self.assertEqual(news_aggregator.GDELT_MASTER_URL, request.call_args_list[0].args[0])
        self.assertEqual(
            "https://storage.googleapis.com/data.gdeltproject.org/"
            "gdeltv2/20260812001500.gkg.csv.zip",
            request.call_args_list[1].args[0],
        )
        for call in request.call_args_list:
            self.assertNotEqual(False, call.kwargs.get("verify", True))

    def test_gdelt_storage_mapping_rejects_unexpected_urls(self):
        self.assertIsNone(
            news_aggregator._gdelt_storage_url(
                "https://attacker.test/gdeltv2/20260812001500.gkg.csv.zip"
            )
        )
        self.assertIsNone(
            news_aggregator._gdelt_storage_url(
                "https://data.gdeltproject.org/"
                "gdeltv2/20260812001500.gkg.csv.zip?download=1"
            )
        )
        self.assertIsNone(
            news_aggregator._gdelt_storage_url(
                "https://data.gdeltproject.org/gdeltv2/latest.gkg.csv.zip"
            )
        )

    def test_thenewsapi_requires_explicit_production_approval(self):
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "THENEWSAPI_PRODUCTION_APPROVED": "false"},
            clear=False,
        ):
            self.assertFalse(news_aggregator._thenewsapi_allowed())
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "THENEWSAPI_PRODUCTION_APPROVED": "true"},
            clear=False,
        ):
            self.assertTrue(news_aggregator._thenewsapi_allowed())


if __name__ == "__main__":
    unittest.main()
