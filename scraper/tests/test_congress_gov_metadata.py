import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from extractors import congress_gov
from source_health import SourceHealthTracker


class _Response:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self.text = "" if payload is None else json.dumps(payload, sort_keys=True)
        self.content = self.text.encode("utf-8")


def _roll_call(key, *references):
    return SimpleNamespace(
        reconciliation_key=key,
        congress=119,
        measure_refs=references,
    )


def _bill_payload(number=8884):
    return {
        "bill": {
            "congress": 119,
            "type": "HR",
            "number": str(number),
            "title": "Making appropriations for the legislative branch",
            "originChamber": "House",
            "introducedDate": "2026-07-23",
            "updateDateIncludingText": "2026-08-10T18:03:00Z",
            "latestAction": {
                "actionDate": "2026-07-23",
                "text": "Introduced in House",
            },
            "legislationUrl": (
                f"https://www.congress.gov/bill/119th-congress/house-bill/{number}"
            ),
        }
    }


def _amendment_payload(number=3937):
    return {
        "amendment": {
            "congress": 119,
            "type": "SAMDT",
            "number": str(number),
            "purpose": "In the nature of a substitute.",
            "description": "An amendment in the nature of a substitute.",
            "chamber": "Senate",
            "submittedDate": "2025-11-10",
            "updateDate": "2025-11-10T21:00:00Z",
            "latestAction": {
                "actionDate": "2025-11-10",
                "text": "Amendment SA 3937 agreed to in Senate by Yea-Nay Vote.",
                "links": [
                    {
                        "name": "Record Vote Number: 616",
                        "url": (
                            "https://www.senate.gov/legislative/LIS/"
                            "roll_call_votes/vote1191/vote_119_1_00616.htm"
                        ),
                    },
                    {
                        "name": "SA 3937",
                        "url": (
                            f"https://www.congress.gov/amendment/119th-congress/"
                            f"senate-amendment/{number}"
                        ),
                    },
                ],
            },
            "amendedBill": {
                "congress": 119,
                "type": "HR",
                "number": "5371",
            },
        }
    }


class CongressGovMeasureReferenceTests(unittest.TestCase):
    def test_parses_only_complete_supported_official_identifiers(self):
        examples = {
            "H R 8884": "bill:119:hr:8884",
            "H.R. 8884": "bill:119:hr:8884",
            "S. 5271": "bill:119:s:5271",
            "H CON RES 89": "bill:119:hconres:89",
            "S.J.Res. 5": "bill:119:sjres:5",
            "S.Amdt. 3937": "amendment:119:samdt:3937",
            "H.Amdt. 112": "amendment:119:hamdt:112",
        }
        for label, expected_key in examples.items():
            with self.subTest(label=label):
                reference = congress_gov.parse_measure_reference(
                    label,
                    congress=119,
                )
                self.assertIsNotNone(reference)
                self.assertEqual(expected_key, reference.source_record_key)

    def test_rejects_ambiguous_house_amendment_and_unsupported_records(self):
        for label in (
            "Amendment No. 12",
            "Greene of Georgia Part A Amendment No. 113",
            "PN1078",
            "Treaty Doc. 118-1",
            "Quorum Call",
            "",
        ):
            with self.subTest(label=label):
                self.assertIsNone(
                    congress_gov.parse_measure_reference(label, congress=119)
                )

    def test_measure_identity_rejects_boolean_or_non_integer_numbers(self):
        for congress, number in ((True, 1), (119, True), (119.0, 1), (119, 1.0)):
            with self.subTest(congress=congress, number=number), self.assertRaises(
                ValueError
            ):
                congress_gov.CongressGovMeasureRef(
                    "bill",
                    congress,
                    "hr",
                    number,
                )


class CongressGovMetadataShadowTests(unittest.TestCase):
    def setUp(self):
        self.bill = congress_gov.CongressGovMeasureRef("bill", 119, "hr", 8884)
        self.amendment = congress_gov.CongressGovMeasureRef(
            "amendment", 119, "samdt", 3937
        )

    def test_fetches_only_deduplicated_detail_endpoints_and_normalizes_metadata(self):
        health = SourceHealthTracker(
            "congress_gov_metadata_shadow",
            min_attempts_for_rate=3,
        )
        amendment_response = _Response(_amendment_payload())
        bill_response = _Response(_bill_payload())

        with patch(
            "extractors.congress_gov.requests.Session"
        ) as session_factory:
            mock_get = session_factory.return_value.get
            mock_get.side_effect = [amendment_response, bill_response]
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [
                    _roll_call("senate:119:2025:616", self.amendment, self.bill),
                    _roll_call("house:119:2026:283", self.bill),
                ],
                api_key="test-key",
                health=health,
            )

        self.assertEqual(2, mock_get.call_count)
        session_factory.return_value.close.assert_called_once_with()
        requested_urls = {call.args[0] for call in mock_get.call_args_list}
        self.assertEqual(
            {
                "https://api.congress.gov/v3/amendment/119/samdt/3937",
                "https://api.congress.gov/v3/bill/119/hr/8884",
            },
            requested_urls,
        )
        for call in mock_get.call_args_list:
            self.assertEqual(
                {"api_key": "test-key", "format": "json"},
                call.kwargs["params"],
            )
        self.assertEqual("healthy", health.status)
        self.assertEqual(2, health.attempts)
        self.assertEqual(2, health.successes)
        self.assertEqual(2, report.roll_calls_seen)
        self.assertEqual(2, report.roll_calls_with_supported_references)
        self.assertEqual(3, report.reference_links_seen)
        self.assertEqual(2, report.distinct_references)
        self.assertEqual(2, report.references_fetched)
        self.assertEqual(1, report.bill_references_fetched)
        self.assertEqual(1, report.amendment_references_fetched)
        self.assertEqual(0, report.references_not_fetched)
        self.assertTrue(report.complete)
        self.assertEqual(
            ("house:119:2026:283", "senate:119:2025:616"),
            report.roll_call_keys_by_reference[self.bill.source_record_key],
        )

        metadata = {
            item.reference.source_record_key: item for item in report.metadata
        }
        normalized_bill = metadata[self.bill.source_record_key]
        self.assertEqual("House", normalized_bill.origin_chamber)
        self.assertEqual("2026-07-23", normalized_bill.introduced_date)
        self.assertEqual(
            hashlib.sha256(bill_response.content).hexdigest(),
            normalized_bill.payload_hash,
        )
        normalized_amendment = metadata[self.amendment.source_record_key]
        self.assertEqual("Senate", normalized_amendment.origin_chamber)
        self.assertEqual("2025-11-10", normalized_amendment.introduced_date)
        self.assertEqual(
            "https://www.congress.gov/amendment/119th-congress/"
            "senate-amendment/3937",
            normalized_amendment.official_url,
        )
        self.assertEqual(
            "bill:119:hr:5371",
            normalized_amendment.amended_bill.source_record_key,
        )
        self.assertNotIn("test-key", normalized_amendment.source_url)

    def test_retries_one_server_failure_as_one_logical_health_attempt(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        with (
            patch("extractors.congress_gov.requests.Session") as session_factory,
            patch("extractors.congress_gov.time.sleep") as mock_sleep,
        ):
            mock_get = session_factory.return_value.get
            mock_get.side_effect = [
                _Response(status_code=503),
                _Response(_bill_payload()),
            ]
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [_roll_call("house:119:2026:283", self.bill)],
                api_key="test-key",
                health=health,
            )

        self.assertEqual(2, mock_get.call_count)
        mock_sleep.assert_called_once_with(0.5)
        self.assertEqual(1, health.attempts)
        self.assertEqual(1, health.successes)
        self.assertEqual(0, health.failures)
        self.assertEqual(1, report.references_fetched)

    def test_identity_mismatch_fails_closed(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        with patch("extractors.congress_gov.requests.Session") as session_factory:
            session_factory.return_value.get.return_value = _Response(
                _bill_payload(number=9999)
            )
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [_roll_call("house:119:2026:283", self.bill)],
                api_key="test-key",
                health=health,
            )

        self.assertTrue(health.breaker_tripped)
        self.assertEqual("identity_mismatch", health.breaker_reason)
        self.assertEqual(1, health.failure_reasons["identity_mismatch"])
        self.assertEqual(0, report.references_fetched)
        self.assertEqual(1, report.references_not_fetched)

    def test_rate_limit_stops_the_remaining_optional_detail_requests(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        with patch("extractors.congress_gov.requests.Session") as session_factory:
            mock_get = session_factory.return_value.get
            mock_get.return_value = _Response(status_code=429)
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [
                    _roll_call("senate:119:2025:616", self.amendment),
                    _roll_call("house:119:2026:283", self.bill),
                ],
                api_key="test-key",
                health=health,
            )

        self.assertEqual(1, mock_get.call_count)
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("http_429", health.breaker_reason)
        self.assertEqual(1, health.skip_reasons["breaker_open"])
        self.assertEqual(2, report.references_not_fetched)

    def test_no_supported_references_is_a_keyless_no_request_result(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        with patch("extractors.congress_gov.requests.get") as mock_get:
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [_roll_call("senate:119:2026:230")],
                api_key="test-key",
                health=health,
            )

        mock_get.assert_not_called()
        self.assertEqual("skipped", health.status)
        self.assertEqual(1, report.roll_calls_without_supported_references)
        self.assertEqual(0, report.distinct_references)
        self.assertFalse(report.complete)

    def test_optional_roll_call_reference_issue_is_aggregate_and_nonblocking(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        roll_call = _roll_call("senate:119:2026:230")
        roll_call.measure_reference_issues = ("invalid_document_congress",)

        with patch("extractors.congress_gov.requests.get") as mock_get:
            report = congress_gov.get_roll_call_measure_metadata_shadow(
                [roll_call],
                api_key="test-key",
                health=health,
            )

        mock_get.assert_not_called()
        self.assertEqual(1, report.roll_calls_with_reference_issues)
        self.assertEqual(1, report.measure_reference_issues)
        self.assertEqual(1, health.skip_reasons["roll_call_reference_issue"])

    def test_reference_cap_raises_before_any_network_request(self):
        health = SourceHealthTracker("congress_gov_metadata_shadow")
        with (
            patch("extractors.congress_gov.requests.get") as mock_get,
            self.assertRaises(ValueError),
        ):
            congress_gov.get_roll_call_measure_metadata_shadow(
                [
                    _roll_call("senate:119:2025:616", self.amendment),
                    _roll_call("house:119:2026:283", self.bill),
                ],
                api_key="test-key",
                health=health,
                max_distinct_references=1,
            )

        mock_get.assert_not_called()
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("reference_cap_exceeded", health.breaker_reason)


if __name__ == "__main__":
    unittest.main()
