import io
import tarfile
import unittest
from unittest.mock import patch

from extractors import federal, gov_api, openstates
from source_health import SourceHealthTracker


class _Response:
    text = "payload"

    def __init__(self, content=b""):
        self.content = content

    def raise_for_status(self):
        return None


class RosterSafetyFloorTests(unittest.TestCase):
    def test_small_congress_snapshot_is_a_blocking_source_failure(self):
        health = SourceHealthTracker("congress")
        tiny_roster = [
            {
                "name": {"official_full": "Only Member"},
                "id": {"bioguide": "O000001"},
                "terms": [{"type": "sen", "state": "CA"}],
            }
        ]
        with patch("extractors.gov_api.requests.get", return_value=_Response()), patch(
            "extractors.gov_api.yaml.safe_load", return_value=tiny_roster
        ):
            with self.assertRaises(ValueError):
                gov_api.get_congress_members(health=health)

        self.assertEqual("failed", health.status)
        self.assertEqual(1, health.failure_reasons["snapshot_below_safety_floor"])

    def test_small_openstates_snapshot_is_a_blocking_source_failure(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz"):
            pass
        health = SourceHealthTracker("openstates")
        with patch(
            "extractors.openstates.requests.get",
            return_value=_Response(content=archive.getvalue()),
        ):
            with self.assertRaises(ValueError):
                openstates.get_state_politicians(health=health)

        self.assertEqual("failed", health.status)
        self.assertEqual(1, health.failure_reasons["snapshot_below_safety_floor"])

    def test_missing_executive_roster_is_a_blocking_source_failure(self):
        health = SourceHealthTracker("executives")
        with patch("extractors.federal.requests.get", return_value=_Response()), patch(
            "extractors.federal.yaml.safe_load", return_value=[]
        ):
            with self.assertRaises(ValueError):
                federal.get_federal_executives(health=health)

        self.assertEqual("failed", health.status)
        self.assertEqual(1, health.failure_reasons["snapshot_below_safety_floor"])


if __name__ == "__main__":
    unittest.main()
