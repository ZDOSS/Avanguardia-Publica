import importlib
import sys
import unittest
from pathlib import Path


class SummaryStub:
    def __init__(self):
        self.counts = {}

    def increment(self, key, amount=1):
        self.counts[key] = self.counts.get(key, 0) + amount


class IdentityResolverTests(unittest.TestCase):
    def setUp(self):
        self.scraper_dir = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(self.scraper_dir))
        self._clear_identity_modules()
        self.identity = importlib.import_module("identity")

    def tearDown(self):
        self._clear_identity_modules()
        try:
            sys.path.remove(str(self.scraper_dir))
        except ValueError:
            pass

    @staticmethod
    def _clear_identity_modules():
        for module_name in list(sys.modules):
            if module_name == "identity" or module_name.startswith("identity."):
                sys.modules.pop(module_name, None)

    def test_identity_keys_from_packet_use_only_trusted_ids(self):
        packet = self.identity.IdentityPacket(
            source_system_key="test-source",
            external_ids={
                "bioguide": "B000001",
                "fec": [" H0CA00001 ", ""],
                "twitter": "not-deterministic",
                "wikidata": "Q123",
            },
        )

        keys = self.identity.identity_keys_from_packet(packet)

        self.assertEqual(
            (
                self.identity.IdentityKey("bioguide", "bioguide_id", "B000001"),
                self.identity.IdentityKey("fec", "fec_candidate_id", "H0CA00001"),
                self.identity.IdentityKey("wikidata", "wikidata_qid", "Q123"),
            ),
            keys,
        )

    def test_trusted_external_keys_from_legacy_row_ignore_untrusted_ids(self):
        keys = self.identity.trusted_external_keys(
            {
                "id": "legacy-1",
                "bioguide_id": "B000001",
                "external_ids": {
                    "fec": [" H0CA00001 ", ""],
                    "twitter": "not-deterministic",
                    "wikidata": "Q123",
                },
            }
        )

        self.assertEqual(
            (
                self.identity.IdentityKey("bioguide", "bioguide_id", "B000001"),
                self.identity.IdentityKey("fec", "fec_candidate_id", "H0CA00001"),
                self.identity.IdentityKey("wikidata", "wikidata_qid", "Q123"),
            ),
            keys,
        )

    def test_packet_from_legacy_politician_preserves_role_context(self):
        packet = self.identity.packet_from_legacy_politician(
            {
                "id": "legacy-1",
                "full_name": "Jane Public",
                "aliases": ["Jane Q. Public"],
                "bioguide_id": "P000001",
                "current_office": "Representative",
                "party": "Independent",
                "state": "CA",
                "district": "12",
                "government_level": "Federal",
                "government_branch": "Legislative",
                "office_type": "House",
                "jurisdiction": "California",
            }
        )

        self.assertEqual("avanguardia-legacy-profile", packet.source_system_key)
        self.assertEqual("legacy-1", packet.legacy_politician_id)
        self.assertEqual(("Jane Public", "Jane Q. Public"), packet.names)
        self.assertEqual("P000001", packet.external_ids["bioguide"])
        self.assertEqual("Federal", packet.role_facts["government_level"])

    def test_existing_deterministic_key_matches_person_and_counts(self):
        summary = SummaryStub()
        key = self.identity.IdentityKey("bioguide", "bioguide_id", "P000001")
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    legacy_politician_id="legacy-existing",
                    deterministic_keys=(key,),
                )
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="bioguide",
                legacy_politician_id="legacy-new",
                external_ids={"bioguide": "P000001"},
            )
        )

        self.assertEqual("matched_existing_person", resolution.action)
        self.assertEqual("person-1", resolution.person_id)
        self.assertEqual(1, summary.counts["identity_deterministic_matches"])
        self.assertEqual(1, summary.counts["identity_legacy_rows_mapped"])

    def test_new_deterministic_key_creates_person_intent(self):
        summary = SummaryStub()
        resolver = self.identity.IdentityResolver(summary=summary)

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="fec",
                legacy_politician_id="legacy-new",
                external_ids={"fec": "H0CA00001"},
            )
        )

        self.assertEqual("create_person", resolution.action)
        self.assertIsNone(resolution.person_id)
        self.assertEqual(1, summary.counts["identity_people_created"])
        self.assertEqual(1, summary.counts["identity_legacy_rows_mapped"])

    def test_missing_deterministic_key_goes_to_review(self):
        summary = SummaryStub()
        resolver = self.identity.IdentityResolver(summary=summary)

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="unconfirmed-media",
                source_record_key="article-1",
                legacy_politician_id="legacy-1",
                names=("  Jane   Public ",),
                external_ids={"twitter": "not-deterministic"},
            )
        )

        self.assertEqual("pending_review", resolution.action)
        self.assertEqual(1, summary.counts["identity_pending_candidates"])
        self.assertEqual(
            "missing_deterministic_identity",
            resolution.pending_candidate.candidate_type,
        )
        self.assertEqual(
            ["jane public"],
            resolution.pending_candidate.evidence["normalized_names"],
        )

    def test_existing_legacy_mapping_matches_without_deterministic_keys(self):
        summary = SummaryStub()
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    legacy_politician_id="legacy-1",
                )
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="legacy",
                legacy_politician_id="legacy-1",
                names=("Legacy Only",),
            )
        )

        self.assertEqual("matched_existing_person", resolution.action)
        self.assertEqual("person-1", resolution.person_id)
        self.assertEqual(1, summary.counts["identity_legacy_rows_mapped"])
        self.assertNotIn("identity_pending_candidates", summary.counts)

    def test_existing_legacy_mapping_matches_new_deterministic_key(self):
        summary = SummaryStub()
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    legacy_politician_id="legacy-1",
                )
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="legacy",
                legacy_politician_id="legacy-1",
                external_ids={"bioguide": "B000001"},
            )
        )

        self.assertEqual("matched_existing_person", resolution.action)
        self.assertEqual("person-1", resolution.person_id)
        self.assertEqual(1, summary.counts["identity_legacy_rows_mapped"])
        self.assertNotIn("identity_people_created", summary.counts)

    def test_deterministic_key_conflicting_with_legacy_mapping_is_blocked(self):
        summary = SummaryStub()
        key = self.identity.IdentityKey("bioguide", "bioguide_id", "B000001")
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    legacy_politician_id="legacy-1",
                ),
                self.identity.ExistingIdentity(
                    person_id="person-2",
                    deterministic_keys=(key,),
                ),
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="legacy",
                legacy_politician_id="legacy-1",
                external_ids={"bioguide": "B000001"},
            )
        )

        self.assertEqual("blocked_conflict", resolution.action)
        self.assertEqual(
            "deterministic_keys_conflict_with_legacy_mapping",
            resolution.blocked_reason,
        )
        self.assertEqual(1, summary.counts["identity_blocked_conflicts"])

    def test_deterministic_key_with_ambiguous_legacy_mapping_is_blocked(self):
        summary = SummaryStub()
        key = self.identity.IdentityKey("bioguide", "bioguide_id", "B000001")
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    deterministic_keys=(key,),
                ),
                self.identity.ExistingIdentity(
                    person_id="person-2",
                    legacy_politician_id="legacy-1",
                ),
                self.identity.ExistingIdentity(
                    person_id="person-3",
                    legacy_politician_id="legacy-1",
                ),
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="legacy",
                legacy_politician_id="legacy-1",
                external_ids={"bioguide": "B000001"},
            )
        )

        self.assertEqual("blocked_conflict", resolution.action)
        self.assertEqual(
            "legacy_politician_id_matches_multiple_people",
            resolution.blocked_reason,
        )
        self.assertEqual(1, summary.counts["identity_blocked_conflicts"])

    def test_conflicting_legacy_mappings_are_blocked(self):
        summary = SummaryStub()
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    legacy_politician_id="legacy-1",
                ),
                self.identity.ExistingIdentity(
                    person_id="person-2",
                    legacy_politician_id="legacy-1",
                ),
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="legacy",
                legacy_politician_id="legacy-1",
            )
        )

        self.assertEqual("blocked_conflict", resolution.action)
        self.assertEqual(
            "legacy_politician_id_matches_multiple_people",
            resolution.blocked_reason,
        )
        self.assertEqual(1, summary.counts["identity_blocked_conflicts"])

    def test_conflicting_deterministic_matches_are_blocked(self):
        summary = SummaryStub()
        key = self.identity.IdentityKey("wikidata", "wikidata_qid", "Q123")
        resolver = self.identity.IdentityResolver(
            [
                self.identity.ExistingIdentity(
                    person_id="person-1",
                    deterministic_keys=(key,),
                ),
                self.identity.ExistingIdentity(
                    person_id="person-2",
                    deterministic_keys=(key,),
                ),
            ],
            summary=summary,
        )

        resolution = resolver.resolve(
            self.identity.IdentityPacket(
                source_system_key="wikidata",
                legacy_politician_id="legacy-1",
                external_ids={"wikidata": "Q123"},
            )
        )

        self.assertEqual("blocked_conflict", resolution.action)
        self.assertEqual(
            "deterministic_keys_match_multiple_people",
            resolution.blocked_reason,
        )
        self.assertEqual(1, summary.counts["identity_blocked_conflicts"])


if __name__ == "__main__":
    unittest.main()
