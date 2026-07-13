from pathlib import Path
import unittest


SQL = Path("infra/db/schema-v2/baseline/0070_geo_placement_packages.sql").read_text(encoding="utf-8")


class SchemaV2GeoPackageContractsTest(unittest.TestCase):
    def test_package_has_exact_brief_evidence_and_prompt_lineage(self) -> None:
        self.assertIn("CREATE TABLE placement_packages", SQL)
        self.assertIn("placement_brief_version_id", SQL)
        self.assertIn("placement_evidence_pack_id", SQL)
        self.assertIn("prompt_bundle_id", SQL)

    def test_prompt_tasks_cover_every_configured_destination_type(self) -> None:
        for task_key in (
            "placement.marketplace.listing",
            "placement.youtube.video_script",
            "placement.reddit.disclosed_official_post",
            "placement.ozbargain.deal_submission",
            "placement.quora.disclosed_expert_answer",
        ):
            self.assertIn(repr(task_key), SQL)

    def test_claims_require_evidence_and_approval_is_maker_checker(self) -> None:
        self.assertIn("REFERENCES placement_evidence_items(id, project_id)", SQL)
        self.assertIn("submitted_for_review_by <> approved_by", SQL)
        self.assertIn("geo placement traceability rows are immutable", SQL)


if __name__ == "__main__":
    unittest.main()
