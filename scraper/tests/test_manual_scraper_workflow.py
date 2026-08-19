import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


class ManualScraperWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scraper_workflow = (
            _REPO_ROOT / ".github" / "workflows" / "scraper.yml"
        ).read_text(encoding="utf-8")
        cls.deploy_workflow = (
            _REPO_ROOT / ".github" / "workflows" / "nextjs.yml"
        ).read_text(encoding="utf-8")

    def test_scraper_has_only_a_manual_trigger(self):
        self.assertIn("name: Manual ETL Scraper", self.scraper_workflow)
        self.assertIn("\non:\n  workflow_dispatch:\n", self.scraper_workflow)
        self.assertNotIn("\n  schedule:", self.scraper_workflow)
        self.assertNotIn("cron:", self.scraper_workflow)

    def test_manual_runs_remain_serial_and_bounded(self):
        self.assertIn("group: nightly-etl", self.scraper_workflow)
        self.assertIn("cancel-in-progress: false", self.scraper_workflow)
        self.assertIn("timeout-minutes: 240", self.scraper_workflow)

    def test_successful_manual_etl_still_triggers_a_frontend_deploy(self):
        self.assertIn(
            'workflows: ["Manual ETL Scraper"]',
            self.deploy_workflow,
        )


if __name__ == "__main__":
    unittest.main()
