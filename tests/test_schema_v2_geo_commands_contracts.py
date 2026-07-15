from pathlib import Path
import unittest


SQL = Path("infra/db/schema-v2/baseline/0080_geo_commands.sql").read_text(encoding="utf-8")


class SchemaV2GeoCommandsContractsTest(unittest.TestCase):
    def test_runtime_commands_are_capability_checked_and_public_is_revoked(self) -> None:
        for name in (
            "geo_v2_create_geo_campaign",
            "geo_v2_create_project_destination",
            "geo_v2_qualify_project_destination",
            "geo_v2_create_placement_opportunity",
        ):
            self.assertIn(name, SQL)
        self.assertIn("geo.campaign.manage", SQL)
        self.assertIn("geo.destination.manage", SQL)
        self.assertIn("geo.opportunity.manage", SQL)
        self.assertIn("FROM PUBLIC", SQL)

    def test_campaign_reads_are_permission_scoped(self) -> None:
        self.assertIn("geo_v2_read_geo_campaigns", SQL)
        self.assertIn("geo.measurement.read", SQL)


if __name__ == "__main__":
    unittest.main()
