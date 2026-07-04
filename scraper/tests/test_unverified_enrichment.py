import unittest

from unverified_enrichment import (
    MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT,
    parse_non_negative_int,
    should_enrich_state_profile,
    state_unverified_enrichment_config,
)


class UnverifiedEnrichmentConfigTests(unittest.TestCase):
    def test_config_defaults_disabled(self):
        config = state_unverified_enrichment_config({})

        self.assertEqual(0, config["limit"])
        self.assertEqual(0, config["offset"])
        self.assertFalse(config["capped"])

    def test_config_parses_limit_and_offset(self):
        config = state_unverified_enrichment_config({
            "STATE_UNVERIFIED_ENRICHMENT_LIMIT": "25",
            "STATE_UNVERIFIED_ENRICHMENT_OFFSET": "100",
        })

        self.assertEqual(25, config["requested_limit"])
        self.assertEqual(25, config["limit"])
        self.assertEqual(100, config["offset"])
        self.assertFalse(config["capped"])

    def test_config_caps_large_limit(self):
        config = state_unverified_enrichment_config({
            "STATE_UNVERIFIED_ENRICHMENT_LIMIT": str(MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT + 1),
        })

        self.assertEqual(MAX_STATE_UNVERIFIED_ENRICHMENT_LIMIT, config["limit"])
        self.assertTrue(config["capped"])

    def test_parse_rejects_invalid_values(self):
        with self.assertRaisesRegex(ValueError, "TEST_LIMIT"):
            parse_non_negative_int("-1", name="TEST_LIMIT")

        with self.assertRaisesRegex(ValueError, "TEST_LIMIT"):
            parse_non_negative_int("many", name="TEST_LIMIT")

    def test_should_enrich_state_profile_uses_zero_based_window(self):
        self.assertFalse(should_enrich_state_profile(9, limit=3, offset=10))
        self.assertTrue(should_enrich_state_profile(10, limit=3, offset=10))
        self.assertTrue(should_enrich_state_profile(12, limit=3, offset=10))
        self.assertFalse(should_enrich_state_profile(13, limit=3, offset=10))


if __name__ == "__main__":
    unittest.main()
