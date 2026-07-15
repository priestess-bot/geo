from pathlib import Path
import unittest


SQL = Path("infra/db/schema-v2/baseline/0060_geo_submission_measurement.sql").read_text(
    encoding="utf-8"
)


class SchemaV2GeoSubmissionContractsTest(unittest.TestCase):
    def test_submission_is_manual_and_requires_qualified_destination(self) -> None:
        self.assertIn("submission_method = 'manual'", SQL)
        self.assertIn("geo_v2_reject_unqualified_destination_submission", SQL)
        self.assertIn("operation_mode = 'manual_submission'", SQL)
        self.assertIn("qualification_status = 'approved'", SQL)

    def test_verification_only_passes_for_indexable_content_match(self) -> None:
        self.assertIn("indexability_status = 'indexable'", SQL)
        self.assertIn("content_match_status = 'matched'", SQL)

    def test_measurement_windows_are_fixed_and_non_causal(self) -> None:
        self.assertIn("'baseline_28d', 'post_28d', 'post_56d', 'post_84d'", SQL)
        self.assertIn("ends_at - starts_at = interval '28 days'", SQL)
        self.assertIn("confounded boolean", SQL)


if __name__ == "__main__":
    unittest.main()
