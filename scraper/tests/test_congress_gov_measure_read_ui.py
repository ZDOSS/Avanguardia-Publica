import unittest
from pathlib import Path


class CongressGovMeasureReadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[2]
        cls.voting_records = (
            repo_root / "frontend" / "src" / "lib" / "votingRecords.ts"
        ).read_text(encoding="utf-8")
        cls.canonical_rpcs = (
            repo_root / "frontend" / "src" / "lib" / "canonicalPoliticians.ts"
        ).read_text(encoding="utf-8")
        cls.voting_tab = (
            repo_root
            / "frontend"
            / "src"
            / "app"
            / "[politician_id]"
            / "VotingRecordTab.tsx"
        ).read_text(encoding="utf-8")

    def test_client_prefers_v3_and_keeps_a_narrow_v2_rollout_fallback(self):
        self.assertIn("'get_canonical_voting_records_v3'", self.canonical_rpcs)
        v3_call = self.voting_records.index(
            "fetchCanonicalVotingRecordsV3(politicianId, range, filters)"
        )
        v2_call = self.voting_records.index(
            "fetchCanonicalVotingRecordsV2(politicianId, range, filters)"
        )
        self.assertLess(v3_call, v2_call)
        self.assertIn(
            "if (!missingCanonicalPoliticianRpc(error)) throw error;",
            self.voting_records,
        )
        self.assertIn(
            "supabase.rpc('get_canonical_voting_records_v3'",
            self.voting_records,
        )

    def test_measure_boundary_revalidates_exact_identity_and_urls(self):
        for contract in (
            "LEGISLATIVE_MEASURE_TYPES",
            "Number.isInteger(congress)",
            "Number.isInteger(measureNumber)",
            "const expectedKey = "
            "`${measureKind}:${congress}:${measureType}:${measureNumber}`",
            "canonicalMeasureKey !== expectedKey",
            "seen.has(canonicalMeasureKey)",
            "safeHttpUrl(optionalText(row.official_url))",
            "value.slice(0, 100)",
        ):
            self.assertIn(contract, self.voting_records)

        self.assertIn(
            "recordOrigin === 'official' ? normalizeLegislativeMeasures(row.measures) : []",
            self.voting_records,
        )

    def test_voting_tab_presents_measure_metadata_without_replacing_vote_context(self):
        for presentation in (
            "item.bill_name",
            "item.vote_result",
            "item.measures.length > 0",
            "measure.canonical_measure_key",
            "measure.measure_kind === 'bill'",
            "measure.title",
            "measure.purpose",
            "measure.observed_at",
            "View on Congress.gov",
        ):
            self.assertIn(presentation, self.voting_tab)

        self.assertIn("href={measure.official_url}", self.voting_tab)
        self.assertIn('target="_blank"', self.voting_tab)
        self.assertIn('rel="noreferrer"', self.voting_tab)
        self.assertNotIn("dangerouslySetInnerHTML", self.voting_tab)


if __name__ == "__main__":
    unittest.main()
