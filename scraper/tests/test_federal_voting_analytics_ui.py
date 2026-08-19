import unittest
from pathlib import Path


class FederalVotingAnalyticsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[2]
        cls.client = (
            repo_root / "frontend" / "src" / "lib" / "votingAnalytics.ts"
        ).read_text(encoding="utf-8")
        cls.panel = (
            repo_root
            / "frontend"
            / "src"
            / "app"
            / "[politician_id]"
            / "VotingAnalyticsPanel.tsx"
        ).read_text(encoding="utf-8")
        cls.connections_client = (
            repo_root / "frontend" / "src" / "lib" / "connections.ts"
        ).read_text(encoding="utf-8")
        cls.connections_tab = (
            repo_root
            / "frontend"
            / "src"
            / "app"
            / "[politician_id]"
            / "ConnectionsTab.tsx"
        ).read_text(encoding="utf-8")
        cls.politician_client = (
            repo_root
            / "frontend"
            / "src"
            / "app"
            / "[politician_id]"
            / "PoliticianClient.tsx"
        ).read_text(encoding="utf-8")
        cls.routes = (
            repo_root / "frontend" / "src" / "lib" / "routes.ts"
        ).read_text(encoding="utf-8")

    def test_client_calls_all_three_versioned_analytics_rpcs(self):
        for rpc in (
            "get_canonical_federal_voting_summary_v1",
            "get_canonical_federal_voting_alignment_v1",
            "get_canonical_federal_voting_comparison_v1",
        ):
            self.assertIn(f"'{rpc}'", self.client)

        for boundary in (
            "isUuid(personId)",
            "isUuid(peerPersonId)",
            "chamberValue(row.chamber)",
            "boundedRate(row.participation_rate)",
            "safeHttpUrl(optionalText(row.source_url))",
            "normalizeLegislativeMeasures(row.measures)",
            "result_limit: range.pageSize + 1",
        ):
            self.assertIn(boundary, self.client)

    def test_profile_exposes_a_complete_analytics_and_evidence_experience(self):
        for presentation in (
            "Federal voting analytics",
            "Covered official votes",
            "Participation",
            "Yea / Nay",
            "Present / Not voting",
            "Official voting alignment",
            "Most aligned",
            "Most often differed",
            "Compare shared votes",
            "Official pairwise evidence",
            "Agreements",
            "Differences",
            "Congress.gov",
            "Source: {record.source_name}",
        ):
            self.assertIn(presentation, self.panel)

        self.assertIn("alignment_minimum_shared_votes", self.panel)
        self.assertIn("Present and Not Voting do not affect alignment", self.panel)
        self.assertIn("PaginationControls", self.panel)
        self.assertNotIn("dangerouslySetInnerHTML", self.panel)

    def test_connections_prefers_official_data_and_separates_legacy_fallback(self):
        official_call = self.connections_client.index(
            "fetchLatestFederalVotingAlignment(politicianId)"
        )
        official_guard = self.connections_client.index(
            "if (official.summary)", official_call
        )
        legacy_call = self.connections_client.index(
            "rpc<CoVoteConnection>('get_covoting'", official_guard
        )
        self.assertLess(official_call, official_guard)
        self.assertLess(official_guard, legacy_call)

        for presentation in (
            "Official Federal Voting Alignment",
            "State & Historical Co-voting",
            "It is not blended into the official federal alignment metric.",
            "Inspect shared votes",
            "votingComparisonPath(currentPoliticianId, c.politician_id)",
        ):
            self.assertIn(presentation, self.connections_tab)

    def test_comparison_links_are_shareable_and_tab_is_visible(self):
        self.assertIn("export function votingComparisonPath", self.routes)
        self.assertIn("tab: 'votes'", self.routes)
        self.assertIn("compare: peerId", self.routes)
        self.assertIn("Voting & Analytics", self.politician_client)


if __name__ == "__main__":
    unittest.main()
