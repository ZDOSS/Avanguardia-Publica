import os
import unittest
from unittest.mock import patch

from extractors import news_aggregator


class _Response:
    ok = True
    status_code = 200

    def json(self):
        return {
            "news": [
                {
                    "title": "A verified headline",
                    "description": "This description must not be persisted.",
                    "url": "https://publisher.test/story",
                    "author": "Publisher",
                }
            ]
        }


class NewsUsagePolicyTests(unittest.TestCase):
    def setUp(self):
        news_aggregator._counters["currents"] = 0

    def test_provider_response_keeps_headline_link_and_provenance_only(self):
        with patch.dict(os.environ, {"CURRENTS_API_KEY": "test"}, clear=False), patch(
            "extractors.news_aggregator.requests.get", return_value=_Response()
        ):
            rows = news_aggregator._fetch_currents("Alex Public")

        self.assertEqual("A verified headline", rows[0]["content_summary"])
        self.assertNotIn("description", rows[0])
        self.assertEqual("Currents", rows[0]["source_api"])
        self.assertEqual("https://publisher.test/story", rows[0]["url"])

    def test_gdelt_is_url_discovery_only_with_attribution(self):
        with patch(
            "extractors.news_aggregator._fetch_gdelt_urls",
            return_value=["https://publisher.test/gdelt-story"],
        ):
            rows = news_aggregator._fetch_gdelt("Alex Public")

        self.assertEqual("GDELT", rows[0]["source_api"])
        self.assertIn("GDELT Project", rows[0]["content_summary"])
        self.assertEqual("gdelt_gkg_url_discovery", rows[0]["ingestion_method"])

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
