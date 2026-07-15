from pathlib import Path
import unittest


SQL = Path("infra/db/schema-v2/baseline/0050_geo_placement_foundation.sql").read_text(
    encoding="utf-8"
)


class SchemaV2GeoPlacementContractsTest(unittest.TestCase):
    def test_campaign_is_scoped_to_one_product_and_market(self) -> None:
        self.assertIn("CREATE TABLE geo_campaigns", SQL)
        self.assertIn("REFERENCES product_entities(id, project_id)", SQL)
        self.assertIn("UNIQUE (project_id, primary_product_entity_id, market_code)", SQL)

    def test_unapproved_destinations_cannot_be_submission_destinations(self) -> None:
        self.assertIn("operation_mode IN ('observed_only', 'manual_submission')", SQL)
        self.assertIn("project_destinations_submission_requires_approval", SQL)
        self.assertIn("'official_community_participation'", SQL)
        self.assertIn("'business_profile'", SQL)

    def test_opportunities_link_to_exact_destination_and_existing_observation_origins(self) -> None:
        self.assertIn("REFERENCES project_destinations(id, project_id)", SQL)
        self.assertIn("REFERENCES source_gaps(id, project_id)", SQL)
        self.assertIn("REFERENCES action_recommendations(id, project_id)", SQL)
        self.assertIn("REFERENCES answer_citations(id, project_id)", SQL)

    def test_project_owned_tables_force_rls_and_deny_runtime_table_dml(self) -> None:
        self.assertIn("FORCE ROW LEVEL SECURITY", SQL)
        self.assertIn("geo_v2_runtime, geo_v2_worker", SQL)


if __name__ == "__main__":
    unittest.main()
