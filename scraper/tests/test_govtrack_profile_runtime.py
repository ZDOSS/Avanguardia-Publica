import re
import unittest
from pathlib import Path

from govtrack_profile_runtime import govtrack_profile_enrichment_mode


_REPO_ROOT = Path(__file__).resolve().parents[2]


class GovTrackProfileRuntimeTests(unittest.TestCase):
    def test_mode_defaults_to_disabled_and_requires_explicit_enabled(self):
        self.assertEqual("disabled", govtrack_profile_enrichment_mode({}))
        self.assertEqual(
            "disabled",
            govtrack_profile_enrichment_mode(
                {"GOVTRACK_PROFILE_ENRICHMENT_MODE": "  "}
            ),
        )
        self.assertEqual(
            "enabled",
            govtrack_profile_enrichment_mode(
                {"GOVTRACK_PROFILE_ENRICHMENT_MODE": " ENABLED "}
            ),
        )
        for invalid in ("true", "1", "auto", "schedule", "typo"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                govtrack_profile_enrichment_mode(
                    {"GOVTRACK_PROFILE_ENRICHMENT_MODE": invalid}
                )

    def test_checked_in_workflow_never_enables_scheduled_profile_crawl(self):
        workflow = (_REPO_ROOT / ".github" / "workflows" / "scraper.yml").read_text(
            encoding="utf-8"
        )
        example_env = (_REPO_ROOT / "scraper" / "example.env").read_text(
            encoding="utf-8"
        )

        self.assertIn("govtrack_profile_enrichment_mode:", workflow)
        expression = re.search(
            r"GOVTRACK_PROFILE_ENRICHMENT_MODE:\s*\$\{\{\s*(.*?)\s*\}\}",
            workflow,
        )
        self.assertIsNotNone(expression)
        self.assertEqual(
            "github.event_name == 'workflow_dispatch' "
            "&& inputs.govtrack_profile_enrichment_mode || 'disabled'",
            expression.group(1),
        )
        self.assertNotIn("vars.GOVTRACK_PROFILE_ENRICHMENT_MODE", workflow)
        self.assertIn("GOVTRACK_PROFILE_ENRICHMENT_MODE=disabled", example_env)

        def resolve(event_name, manual_input, _repository_variable):
            if event_name == "workflow_dispatch":
                return manual_input or "disabled"
            return "disabled"

        self.assertEqual(resolve("schedule", "enabled", "enabled"), "disabled")
        self.assertEqual(resolve("push", "enabled", "enabled"), "disabled")
        self.assertEqual(
            resolve("workflow_dispatch", "disabled", "enabled"),
            "disabled",
        )
        self.assertEqual(
            resolve("workflow_dispatch", "enabled", "disabled"),
            "enabled",
        )


if __name__ == "__main__":
    unittest.main()
