from __future__ import annotations

import importlib
from pathlib import Path
import re
import unittest

from geo_core.repositories import (
    assert_repository_boundary_compatibility,
    missing_repository_boundary_methods,
    repository_boundaries,
)
from geo_core.repository import PostgresEvidenceRepository


class RepositoryBoundaryTest(unittest.TestCase):
    def test_repository_sql_templates_do_not_leave_unformatted_placeholders(self) -> None:
        repository_path = Path(__file__).resolve().parents[1] / "packages" / "geo_core" / "geo_core" / "repository.py"
        source = repository_path.read_text(encoding="utf-8")
        cursor_execute_template = re.compile(
            r"cursor\.execute\(\s*\n(?P<indent>\s*)(?P<f>f?)\"\"\"(?P<body>.*?)\"\"\"",
            re.S,
        )
        offenders: list[str] = []
        for match in cursor_execute_template.finditer(source):
            body = match.group("body")
            if "{" not in body or match.group("f"):
                continue
            line_number = source.count("\n", 0, match.start()) + 1
            first_placeholder_line = next((line.strip() for line in body.splitlines() if "{" in line), "").strip()
            offenders.append(f"{line_number}: {first_placeholder_line}")

        self.assertEqual(offenders, [])

    def test_repository_boundaries_are_frozen_for_w1_i02(self) -> None:
        boundaries = {boundary.boundary_id: boundary for boundary in repository_boundaries()}

        self.assertEqual(set(boundaries), {"access_control", "audit", "project"})
        self.assertEqual(boundaries["audit"].module, "geo_core.repositories.audit_repository")
        self.assertEqual(boundaries["project"].module, "geo_core.repositories.project_repository")
        self.assertEqual(boundaries["access_control"].module, "geo_core.repositories.access_control_repository")
        self.assertTrue(all(boundary.scope_required for boundary in boundaries.values()))

    def test_repository_boundary_modules_are_importable(self) -> None:
        for boundary in repository_boundaries():
            with self.subTest(boundary=boundary.boundary_id):
                module = importlib.import_module(boundary.module)
                self.assertTrue(hasattr(module, boundary.protocol_name))

    def test_current_postgres_repository_satisfies_frozen_boundaries(self) -> None:
        missing = missing_repository_boundary_methods(PostgresEvidenceRepository)

        self.assertEqual(missing, {})
        assert_repository_boundary_compatibility(PostgresEvidenceRepository)

    def test_boundary_compatibility_reports_missing_methods(self) -> None:
        class PartialRepository:
            def save_audit_events(self) -> None:
                return None

        missing = missing_repository_boundary_methods(PartialRepository)

        self.assertIn("audit", missing)
        self.assertIn("project", missing)
        self.assertIn("access_control", missing)
        with self.assertRaisesRegex(AssertionError, "Repository boundary compatibility failed"):
            assert_repository_boundary_compatibility(PartialRepository)


if __name__ == "__main__":
    unittest.main()
