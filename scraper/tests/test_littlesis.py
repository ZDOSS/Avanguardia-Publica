import unittest

from extractors import littlesis


class LittleSisRelationshipTests(unittest.TestCase):
    def tearDown(self):
        littlesis.reset_budget()

    def test_relationships_parse_current_top_level_entity_links(self):
        def fake_get(path, params=None):
            self.assertEqual("/api/entities/13516/relationships", path)
            self.assertIsNone(params)
            return {
                "data": [
                    {
                        "type": "relationships",
                        "id": 2061853,
                        "attributes": {
                            "entity1_id": 137458,
                            "entity2_id": 13516,
                            "category_id": 5,
                            "description1": "Campaign Contribution",
                        },
                        "entity": "https://littlesis.org/person/137458-Anne_M_Redman",
                        "related": "https://littlesis.org/person/13516-Nancy_Pelosi",
                    }
                ]
            }

        original_get = littlesis._get
        littlesis._get = fake_get
        try:
            rows = littlesis._relationships_for_entity("13516")
        finally:
            littlesis._get = original_get

        self.assertEqual(
            [
                {
                    "related_name": "Anne M Redman",
                    "relationship_type": "Donation",
                    "url": "https://littlesis.org/person/137458-Anne_M_Redman",
                    "source_api": "LittleSis",
                }
            ],
            rows,
        )

    def test_relationships_keep_json_api_links_shape(self):
        def fake_get(path, params=None):
            return {
                "data": [
                    {
                        "attributes": {
                            "category_id": 3,
                            "description1": "Board Membership",
                        },
                        "links": {
                            "entity": {
                                "href": "https://littlesis.org/org/123-Acme_Foundation"
                            },
                            "related": {
                                "href": "https://littlesis.org/person/456-Test_Official"
                            },
                        },
                    }
                ]
            }

        original_get = littlesis._get
        littlesis._get = fake_get
        try:
            rows = littlesis._relationships_for_entity("456")
        finally:
            littlesis._get = original_get

        self.assertEqual("Acme Foundation", rows[0]["related_name"])
        self.assertEqual("Membership", rows[0]["relationship_type"])
        self.assertEqual("https://littlesis.org/org/123-Acme_Foundation", rows[0]["url"])


if __name__ == "__main__":
    unittest.main()
