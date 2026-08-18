import unittest
from pathlib import Path


class CongressGovMeasureReadMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        migration_path = (
            Path(__file__).resolve().parents[2]
            / "migrations"
            / "0037_congress_gov_measure_read_surface.sql"
        )
        cls.sql = migration_path.read_text(encoding="utf-8")
        function_start = cls.sql.index(
            "CREATE FUNCTION public.get_canonical_voting_records_v3"
        )
        function_end = cls.sql.index("$function$;", function_start)
        cls.function_sql = cls.sql[function_start:function_end]

    def test_requires_exact_reviewed_vote_and_measure_predecessors(self):
        for migration_key, version in (
            ("0033_official_voting_records_deduplication_repair", 33),
            ("0036_congress_gov_scheduled_enablement", 36),
        ):
            self.assertIn(f"migration_key = '{migration_key}'", self.sql)
            self.assertIn(f"migration_version = {version}", self.sql)

        self.assertIn(
            "v_body_md5 IS DISTINCT FROM "
            "'29cee3603f567c2429947232d0279eff'",
            self.sql,
        )
        self.assertIn("v_language IS DISTINCT FROM 'plpgsql'", self.sql)
        self.assertIn("v_security_definer IS DISTINCT FROM true", self.sql)
        self.assertIn("ARRAY['search_path=\"\"']::text[]", self.sql)

    def test_rpc_delegates_vote_identity_deduplication_and_pagination_to_v2(self):
        self.assertIn("LANGUAGE sql", self.function_sql)
        self.assertIn("STABLE", self.function_sql)
        self.assertIn("SECURITY DEFINER", self.function_sql)
        self.assertIn("SET search_path = ''", self.function_sql)
        self.assertIn(
            "FROM public.get_canonical_voting_records_v2(",
            self.function_sql,
        )
        for argument in (
            "p_id",
            "result_limit",
            "result_offset",
            "vote_cast_filter",
        ):
            self.assertIn(argument, self.function_sql)

        self.assertNotIn(
            "FROM public.voting_records",
            self.function_sql,
        )
        self.assertNotIn(
            "FROM public.person_roll_call_votes",
            self.function_sql,
        )

    def test_exact_links_are_aggregated_without_duplicating_vote_rows(self):
        self.assertIn("LEFT JOIN LATERAL", self.function_sql)
        self.assertIn("jsonb_agg(", self.function_sql)
        self.assertIn("AS measures", self.function_sql)
        self.assertIn("LIMIT 100", self.function_sql)
        self.assertIn(
            "measure_link.roll_call_source_record_id = roll_call.source_record_id",
            self.function_sql,
        )
        self.assertIn(
            "measure_link.link_basis = 'exact_official_measure_identifier'",
            self.function_sql,
        )
        self.assertIn(
            "roll_call.canonical_roll_call_key = vote.roll_call_id",
            self.function_sql,
        )
        self.assertIn(
            "roll_call_source.source_url = vote.source_url",
            self.function_sql,
        )
        self.assertIn(
            "roll_call_source.source_system_key = 'house-clerk'",
            self.function_sql,
        )
        self.assertIn(
            "roll_call_source.source_system_key = 'senate-lis'",
            self.function_sql,
        )
        self.assertIn(
            "measure.congress = roll_call.congress",
            self.function_sql,
        )
        self.assertIn(
            "WHEN vote.record_origin = 'official'",
            self.function_sql,
        )
        self.assertIn("ELSE '[]'::jsonb", self.function_sql)

    def test_rpc_exposes_only_active_verified_reviewed_congress_gov_facts(self):
        for contract in (
            "measure_source.source_system_key = 'congress-gov'",
            "measure_source.source_record_key = measure.canonical_measure_key",
            "measure_source.record_type = 'legislative_measure'",
            "measure_source.person_id IS NULL",
            "measure_source.legacy_politician_id IS NULL",
            "measure_source.source_catalog_slug = 'congress-gov-api'",
            "measure_source.source_endpoint_slug = 'api-v3'",
            "measure_source.source_url = format(",
            "measure_source.verified_lane = 'verified'",
            "measure_source.record_status = 'active'",
            "measure_source.retired_at IS NULL",
            "measure_source_system.source_kind = 'government'",
            "measure_source_system.trust_level = 'official'",
            "measure_source_system.verified = true",
            "measure_catalog_source.status = 'approved'",
            "measure_catalog_source.repo_fit = 'wired'",
            "measure_catalog_source.verified_lane = 'verified'",
            "measure_catalog_link.source_system_key =",
            "measure_catalog_link.link_type = 'same_source'",
            "measure_catalog_endpoint.status = 'approved'",
        ):
            self.assertIn(contract, self.function_sql)

        for private_field in (
            "raw_payload_ref",
            "payload_hash",
            "measure.metadata",
            "measure_link.metadata",
            "measure_source.metadata",
            "description",
            "latest_action_text",
        ):
            self.assertNotIn(private_field, self.function_sql)

    def test_presentation_contract_is_narrow_and_official_urls_fail_closed(self):
        for presentation_field in (
            "'canonical_measure_key'",
            "'measure_kind'",
            "'congress'",
            "'measure_type'",
            "'measure_number'",
            "'title'",
            "'purpose'",
            "'official_url'",
            "'source_name'",
            "'observed_at'",
        ):
            self.assertIn(presentation_field, self.function_sql)

        self.assertIn(
            "measure.official_url LIKE 'https://www.congress.gov/%'",
            self.function_sql,
        )
        self.assertIn("char_length(measure.title) > 1000", self.function_sql)
        self.assertIn("left(measure.title, 999)", self.function_sql)
        self.assertIn("char_length(measure.purpose) > 2000", self.function_sql)
        self.assertIn("left(measure.purpose, 1999)", self.function_sql)

    def test_private_tables_stay_closed_and_only_the_rpc_is_granted(self):
        for table in (
            "public.source_records",
            "public.legislative_roll_calls",
            "public.legislative_measures",
            "public.legislative_roll_call_measure_links",
        ):
            self.assertNotIn(f"GRANT SELECT ON TABLE {table}", self.sql)

        self.assertIn(
            "REVOKE EXECUTE ON FUNCTION public.get_canonical_voting_records_v3",
            self.sql,
        )
        self.assertIn(") TO anon, authenticated;", self.sql)
        self.assertIn("has_table_privilege('anon'", self.sql)
        self.assertIn("has_table_privilege('authenticated'", self.sql)

    def test_records_forward_only_marker_and_advances_scraper_preflight(self):
        self.assertIn(
            "'0037_congress_gov_measure_read_surface',\n    37,",
            self.sql,
        )
        self.assertIn("'scraper_preflight_required', true", self.sql)
        self.assertIn("'legacy_vote_contract_changed', false", self.sql)
        self.assertIn("'scraper_write_contract_changed', false", self.sql)
        self.assertIn("NOTIFY pgrst, 'reload schema';", self.sql)
        self.assertTrue(self.sql.rstrip().endswith("COMMIT;"))


if __name__ == "__main__":
    unittest.main()
