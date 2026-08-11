import unittest
from datetime import date
import hashlib
import json
from unittest.mock import patch

from extractors import senate_roll_calls
from source_health import SourceHealthTracker


_HISTORICAL_YAML = """
- id:
    lis: S999
    bioguide: Z000001
  terms:
    - type: sen
      start: 2000-01-01
      end: 2006-12-31
- id:
    lis: X123
    bioguide: Z000002
  terms:
    - type: rep
      start: 2010-01-01
      end: 2014-12-31
"""


def _roll_call_xml(vote_number: int, first_vote: str) -> str:
    yeas = 1 if first_vote.lower() in {"aye", "yea", "yes"} else 0
    nays = 1 + (1 if first_vote.lower() in {"nay", "no"} else 0)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<roll_call_vote>
  <congress>119</congress>
  <session>2</session>
  <congress_year>2026</congress_year>
  <vote_number>{vote_number}</vote_number>
  <vote_date>June 24, 2026,  10:30 PM</vote_date>
  <vote_question_text>On the Motion to Proceed S.J.Res. {vote_number}</vote_question_text>
  <vote_result>Motion Agreed to</vote_result>
  <document>
    <document_congress>119</document_congress>
    <document_type>S.J.Res.</document_type>
    <document_number>{vote_number}</document_number>
  </document>
  <count>
    <yeas>{yeas}</yeas>
    <nays>{nays}</nays>
    <present>1</present>
    <absent>1</absent>
  </count>
  <members>
    <member><lis_member_id>S001</lis_member_id><vote_cast>{first_vote}</vote_cast></member>
    <member><lis_member_id>S002</lis_member_id><vote_cast>Nay</vote_cast></member>
    <member><lis_member_id>S999</lis_member_id><vote_cast>Present</vote_cast></member>
    <member><vote_cast>Not Voting</vote_cast></member>
  </members>
</roll_call_vote>"""


def _govtrack_voters(vote_number: int, vote_id: int = 128911) -> str:
    vote = {
        "congress": 119,
        "chamber": "senate",
        "session": "2026",
        "number": vote_number,
    }
    return json.dumps(
        {
            "meta": {"limit": 600, "offset": 0, "total_count": 3},
            "objects": [
                {
                    "person": {"bioguideid": "A000001"},
                    "option": {"value": "Yea", "vote": vote_id},
                    "vote": vote,
                },
                {
                    "person": {"bioguideid": "B000002"},
                    "option": {"value": "Nay", "vote": vote_id},
                    "vote": vote,
                },
                {
                    "person": {"bioguideid": "Z000001"},
                    "option": {"value": "Present", "vote": vote_id},
                    "vote": vote,
                },
            ],
        }
    )


class _Response:
    def __init__(self, status_code=200, text="", content=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8") if content is None else content


class SenateRollCallShadowTests(unittest.TestCase):
    def test_current_congress_session_handles_the_january_transition(self):
        self.assertEqual(
            (119, 1),
            senate_roll_calls._current_congress_session(date(2026, 1, 2)),
        )
        self.assertEqual(
            (119, 2),
            senate_roll_calls._current_congress_session(date(2026, 7, 13)),
        )
        self.assertEqual(
            (119, 2),
            senate_roll_calls._current_congress_session(date(2027, 1, 2)),
        )

    def test_menu_parser_uses_only_the_requested_congress_and_session(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
            <a href="vote_119_1_00200.htm">prior session</a>
            <a href="vote_118_2_00300.htm">prior congress</a>
        """
        self.assertEqual([2, 1], senate_roll_calls._parse_menu(menu, 119, 2))

    def test_fetch_provenance_hashes_raw_response_bytes(self):
        raw_content = b"\xffofficial-senate-bytes"
        health = SourceHealthTracker("senate_roll_call_shadow")

        with patch(
            "extractors.senate_roll_calls.requests.get",
            return_value=_Response(text="decoded replacement", content=raw_content),
        ):
            document = senate_roll_calls._fetch_parsed(
                "https://example.test/official.xml",
                lambda fetched: fetched,
                health=health,
                state=senate_roll_calls._FetchState(),
            )

        self.assertIsNotNone(document)
        self.assertEqual(raw_content, document.content)
        self.assertEqual(
            hashlib.sha256(raw_content).hexdigest(),
            document.payload_hash,
        )

    def test_shadow_fetches_a_bounded_window_and_compares_only_exact_lis_ids(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        govtrack_votes = {
            "S001": {
                "senate:119:2026:2": "Yea",
                "senate:119:2026:1": "Yea",
            }
        }

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text="[]"),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001", "S002"},
                govtrack_votes,
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual("healthy", health.status)
        self.assertEqual(4, health.attempts)
        self.assertEqual(4, health.successes)
        self.assertEqual(2, report.roll_calls_listed)
        self.assertEqual(2, report.roll_calls_fetched)
        self.assertEqual(8, report.member_votes_seen)
        self.assertEqual(2, report.member_votes_missing_lis_id)
        self.assertEqual(4, report.exact_lis_matches)
        self.assertEqual({"S999"}, report.unmatched_lis_ids)
        self.assertEqual(1, report.govtrack_vote_cast_matches)
        self.assertEqual(1, report.govtrack_vote_cast_mismatches)
        self.assertEqual(2, report.govtrack_vote_not_observed)
        self.assertEqual(
            1,
            report.counters()["senate_roll_call_shadow_unmatched_lis_ids"],
        )

    def test_shadow_uses_complete_vote_centric_snapshot_and_historical_crosswalk(self):
        menu = '<a href="vote_119_2_00002.htm">2</a>'
        health = SourceHealthTracker(
            "senate_roll_call_shadow", min_attempts_for_rate=3
        )

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=_HISTORICAL_YAML),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text='<main data-vote-id="128911">Vote</main>'),
                _Response(text=_govtrack_voters(2)),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001", "S002"},
                bioguide_ids_by_lis_id={
                    "S001": "A000001",
                    "S002": "B000002",
                },
                limit=1,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(5, mock_get.call_count)
        self.assertEqual(
            "https://www.govtrack.us/congress/votes/119-2026/s2",
            mock_get.call_args_list[3].args[0],
        )
        self.assertEqual(
            "https://www.govtrack.us/api/v2/vote_voter/?vote=128911&limit=600",
            mock_get.call_args_list[4].args[0],
        )
        self.assertEqual("healthy", health.status)
        self.assertEqual(5, health.attempts)
        self.assertEqual(5, health.successes)
        self.assertEqual(1, report.roll_calls_fetched)
        self.assertEqual(3, report.exact_lis_matches)
        self.assertEqual(1, report.historical_lis_ids_loaded)
        self.assertEqual(0, report.member_votes_missing_bioguide_crosswalk)
        self.assertEqual(1, report.govtrack_roll_calls_reconciled)
        self.assertEqual(0, report.govtrack_roll_calls_not_observed)
        self.assertEqual(3, report.govtrack_vote_cast_matches)
        self.assertEqual(0, report.govtrack_vote_cast_mismatches)
        self.assertEqual(0, report.govtrack_vote_not_observed)
        self.assertTrue(report.snapshot_complete)
        self.assertEqual(1, len(report.roll_calls))
        self.assertRegex(report.roll_calls[0].payload_hash or "", r"^[0-9a-f]{64}$")
        self.assertEqual(
            ["bill:119:sjres:2"],
            [
                reference.source_record_key
                for reference in report.roll_calls[0].measure_refs
            ],
        )

    def test_structured_amendment_and_underlying_bill_refs_are_both_retained(self):
        xml = _roll_call_xml(2, "Yea").replace(
            """<document>
    <document_congress>119</document_congress>
    <document_type>S.J.Res.</document_type>
    <document_number>2</document_number>
  </document>""",
            """<document>
    <document_congress>119</document_congress>
    <document_type>S.Amdt.</document_type>
    <document_number/>
  </document>
  <amendment>
    <amendment_number>S.Amdt. 3937</amendment_number>
    <amendment_to_document_number>H.R. 5371</amendment_to_document_number>
    <amendment_purpose>In the nature of a substitute.</amendment_purpose>
  </amendment>""",
        )

        roll_call = senate_roll_calls._parse_roll_call(
            xml,
            (
                "https://www.senate.gov/legislative/LIS/roll_call_votes/"
                "vote1192/vote_119_2_00002.xml"
            ),
            119,
            2,
            2,
        )

        self.assertEqual(
            ["amendment:119:samdt:3937", "bill:119:hr:5371"],
            [reference.source_record_key for reference in roll_call.measure_refs],
        )

    def test_invalid_optional_measure_congress_does_not_block_official_vote(self):
        xml = _roll_call_xml(2, "Yea").replace(
            "<document_congress>119</document_congress>",
            "<document_congress>not-a-congress</document_congress>",
        )

        roll_call = senate_roll_calls._parse_roll_call(
            xml,
            (
                "https://www.senate.gov/legislative/LIS/roll_call_votes/"
                "vote1192/vote_119_2_00002.xml"
            ),
            119,
            2,
            2,
        )

        self.assertEqual((), roll_call.measure_refs)
        self.assertEqual(
            ("invalid_document_congress",),
            roll_call.measure_reference_issues,
        )

    def test_normalized_roll_call_builds_stable_lis_and_bioguide_payloads(self):
        roll_call = senate_roll_calls.SenateRollCall(
            congress=119,
            session=2,
            congress_year=2026,
            vote_number=2,
            vote_date="2026-07-14",
            question="On Passage",
            source_url=(
                "https://www.senate.gov/legislative/LIS/roll_call_votes/"
                "vote1192/vote_119_2_00002.xml"
            ),
            member_votes=(
                senate_roll_calls.SenateMemberVote("S001", "Yea", "A000001"),
                senate_roll_calls.SenateMemberVote("S002", "Nay", "B000002"),
                senate_roll_calls.SenateMemberVote("S999", "Present", "Z000001"),
            ),
            vote_result="Motion Agreed to",
            payload_hash="a" * 64,
            fetched_at="2026-07-21T12:00:00+00:00",
            official_member_vote_total=3,
        )

        roll_call_payload, member_votes = roll_call.rpc_payload()

        self.assertEqual("senate:119:2026:2", roll_call_payload["source_record_key"])
        self.assertEqual("Motion Agreed to", roll_call_payload["vote_result"])
        self.assertRegex(roll_call_payload["payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            [
                "senate:119:2026:2:S001",
                "senate:119:2026:2:S002",
                "senate:119:2026:2:S999",
            ],
            [member_vote["source_record_key"] for member_vote in member_votes],
        )
        self.assertEqual(
            ["A000001", "B000002", "Z000001"],
            [member_vote["bioguide_id"] for member_vote in member_votes],
        )

    def test_shadow_reports_newer_official_vote_missing_from_govtrack_as_lag(self):
        menu = '<a href="vote_119_2_00002.htm">2</a>'
        health = SourceHealthTracker(
            "senate_roll_call_shadow", min_attempts_for_rate=3
        )

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=_HISTORICAL_YAML),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(status_code=404),
            ],
        ):
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001", "S002"},
                bioguide_ids_by_lis_id={
                    "S001": "A000001",
                    "S002": "B000002",
                },
                limit=1,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual("degraded", health.status)
        self.assertEqual(4, health.attempts)
        self.assertEqual(3, health.successes)
        self.assertEqual(0, health.failures)
        self.assertEqual(1, health.skips)
        self.assertEqual(
            1,
            health.skip_reasons["govtrack_roll_call_not_available"],
        )
        self.assertEqual(0, report.govtrack_roll_calls_reconciled)
        self.assertEqual(1, report.govtrack_roll_calls_not_observed)
        self.assertEqual(3, report.govtrack_vote_not_observed)
        self.assertEqual(
            3,
            report.govtrack_vote_not_observed_unavailable_roll_call,
        )
        self.assertEqual(0, report.govtrack_vote_not_observed_with_snapshot)

    def test_shadow_returns_early_without_lis_join_keys(self):
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        with patch("extractors.senate_roll_calls.requests.get") as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"", "  "},
                {},
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(0, mock_get.call_count)
        self.assertEqual(0, report.roll_calls_listed)
        self.assertEqual(1, health.skips)
        self.assertEqual(1, health.skip_reasons.get("no_lis_join_keys", 0))
        self.assertEqual("skipped", health.status)

    def test_rate_limit_is_visible_and_stops_the_optional_shadow_source(self):
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        with patch(
            "extractors.senate_roll_calls.requests.get",
            return_value=_Response(status_code=429),
        ):
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001"},
                {},
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(0, report.roll_calls_fetched)
        self.assertTrue(health.breaker_tripped)
        self.assertEqual("http_429", health.breaker_reason)
        self.assertEqual("failed", health.status)

    def test_shadow_uses_historical_senate_lis_ids_when_available(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
        govtrack_votes = {
            "S001": {
                "senate:119:2026:2": "Yea",
                "senate:119:2026:1": "Yea",
            },
            "S999": {
                "senate:119:2026:2": "Present",
                "senate:119:2026:1": "Present",
            },
        }

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=_HISTORICAL_YAML),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {"S001"},
                govtrack_votes,
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual(8, report.member_votes_seen)
        self.assertEqual(2, report.member_votes_missing_lis_id)
        self.assertEqual({"S002"}, report.unmatched_lis_ids)
        self.assertEqual(4, report.exact_lis_matches)
        self.assertEqual(3, report.govtrack_vote_cast_matches)
        self.assertEqual(1, report.govtrack_vote_cast_mismatches)
        self.assertEqual(0, report.govtrack_vote_not_observed)
        self.assertEqual(1, report.historical_lis_ids_loaded)

    def test_historical_lis_ids_failure_modes_are_nonfatal(self):
        failure_cases = [
            (
                _Response(status_code=200, text="not-a-yaml-list"),
                "historical_parse_error",
            ),
            (
                _Response(status_code=500, text="service unavailable"),
                "historical_http_500",
            ),
        ]

        for response, reason in failure_cases:
            with self.subTest(reason=reason):
                health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)
                with patch(
                    "extractors.senate_roll_calls.requests.get",
                    return_value=response,
                ) as mock_get:
                    ids = senate_roll_calls._historical_senate_lis_ids(health=health)

                self.assertEqual(set(), ids)
                self.assertEqual(1, mock_get.call_count)
                self.assertEqual(1, health.skips)
                self.assertEqual(1, health.skip_reasons.get(reason, 0))

    def test_shadow_normalizes_roster_and_historical_lis_ids(self):
        menu = """
            <a href="vote_119_2_00002.htm">2</a>
            <a href="vote_119_2_00001.htm">1</a>
        """
        historical_yaml = """
- id:
    lis: s999
    bioguide: Z000001
  terms:
    - type: sen
      start: 2000-01-01
      end: 2006-12-31
"""
        health = SourceHealthTracker("senate_roll_call_shadow", min_attempts_for_rate=3)

        with patch(
            "extractors.senate_roll_calls.requests.get",
            side_effect=[
                _Response(text=historical_yaml),
                _Response(text=menu),
                _Response(text=_roll_call_xml(2, "Yea")),
                _Response(text=_roll_call_xml(1, "Nay")),
            ],
        ) as mock_get:
            report = senate_roll_calls.get_recent_senate_roll_call_shadow(
                {" s001 "},
                {
                    "S001": {
                        "senate:119:2026:2": "Yea",
                        "senate:119:2026:1": "Yea",
                    },
                    "s999": {
                        "senate:119:2026:2": "Present",
                        "senate:119:2026:1": "Present",
                    },
                },
                limit=2,
                health=health,
                today=date(2026, 7, 13),
            )

        self.assertEqual(4, mock_get.call_count)
        self.assertEqual(1, report.historical_lis_ids_loaded)
        self.assertEqual({"S002"}, report.unmatched_lis_ids)

    def test_govtrack_reconciliation_requires_its_exact_senate_vote_url(self):
        records = [
            {
                "bill_summary": "Result - https://www.govtrack.us/congress/votes/119-2026/s192",
                "vote_cast": "Yea",
            },
            {
                "bill_summary": "A similarly named House vote",
                "vote_cast": "Nay",
            },
        ]

        self.assertEqual(
            {"senate:119:2026:192": "Yea"},
            senate_roll_calls.govtrack_senate_vote_casts(records),
        )

    def test_govtrack_voter_parser_rejects_incomplete_or_wrong_vote(self):
        incomplete = json.loads(_govtrack_voters(2))
        incomplete["meta"]["total_count"] = 2
        with self.assertRaisesRegex(ValueError, "pagination"):
            senate_roll_calls._parse_govtrack_voters(
                json.dumps(incomplete),
                expected_vote_id=128911,
                expected_congress=119,
                expected_year=2026,
                expected_vote_number=2,
            )

        wrong_vote = json.loads(_govtrack_voters(2))
        wrong_vote["objects"][0]["vote"]["chamber"] = "house"
        with self.assertRaisesRegex(ValueError, "requested vote"):
            senate_roll_calls._parse_govtrack_voters(
                json.dumps(wrong_vote),
                expected_vote_id=128911,
                expected_congress=119,
                expected_year=2026,
                expected_vote_number=2,
            )

    def test_govtrack_voter_parser_preserves_nonstandard_senate_casts(self):
        payload = json.loads(_govtrack_voters(2))
        payload["objects"][0]["option"]["value"] = "Guilty"

        parsed = senate_roll_calls._parse_govtrack_voters(
            json.dumps(payload),
            expected_vote_id=128911,
            expected_congress=119,
            expected_year=2026,
            expected_vote_number=2,
        )

        self.assertEqual("Guilty", parsed["A000001"])

    def test_govtrack_vote_page_requires_exactly_one_internal_vote_id(self):
        self.assertEqual(
            128911,
            senate_roll_calls._parse_govtrack_vote_id(
                '<main data-vote-id="128911">Vote</main>'
            ),
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            senate_roll_calls._parse_govtrack_vote_id(
                '<i data-vote-id="1"></i><i data-vote-id="2"></i>'
            )

    def test_roll_call_parser_rejects_a_response_for_the_wrong_vote(self):
        with self.assertRaises(ValueError):
            senate_roll_calls._parse_roll_call(
                _roll_call_xml(2, "Yea"),
                "https://example.test/vote_119_2_00001.xml",
                119,
                2,
                1,
            )

    def test_roll_call_parser_rejects_member_rows_that_disagree_with_totals(self):
        xml = _roll_call_xml(2, "Yea").replace("<yeas>1</yeas>", "<yeas>2</yeas>")

        with self.assertRaisesRegex(ValueError, "official vote totals"):
            senate_roll_calls._parse_roll_call(
                xml,
                "https://example.test/vote_119_2_00002.xml",
                119,
                2,
                2,
            )

    def test_write_block_reasons_cover_every_reconciliation_gap(self):
        report = senate_roll_calls.SenateRollCallShadowReport(
            roll_calls_listed=1,
            roll_calls_fetched=1,
            member_votes_seen=4,
            member_votes_missing_lis_id=1,
            member_votes_missing_vote_cast=1,
            unmatched_lis_ids={"S999"},
            member_votes_missing_bioguide_crosswalk=1,
            govtrack_roll_calls_not_observed=1,
            govtrack_vote_cast_mismatches=1,
            govtrack_vote_not_observed=1,
            listing_complete=True,
        )
        health = SourceHealthTracker("senate_roll_call_shadow")
        health.record_attempt()
        health.record_success()

        self.assertEqual(
            (
                "incomplete_snapshot",
                "missing_lis_ids",
                "missing_vote_casts",
                "unmatched_lis_ids",
                "missing_bioguide_crosswalks",
                "reconciliation_roll_calls_not_observed",
                "reconciliation_mismatches",
                "reconciliation_votes_not_observed",
            ),
            report.authoritative_write_block_reasons(health),
        )


if __name__ == "__main__":
    unittest.main()
