from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_default_admin_suite_excludes_surfaces_with_dedicated_fixture_configs() -> None:
    default_config = (ROOT / "playwright.config.ts").read_text(encoding="utf-8")
    required_runner = (ROOT / "scripts/run-required-browser-tests.mjs").read_text(
        encoding="utf-8"
    )
    workflow_config = (ROOT / "playwright.workflow-c.config.ts").read_text(
        encoding="utf-8"
    )

    assert '"admin-workflow-c.spec.ts"' in default_config
    assert 'testMatch: "admin-workflow-c.spec.ts"' in workflow_config
    assert '"--config=playwright.workflow-c.config.ts"' in required_runner
    assert '"--project=chromium-workflow-c"' in required_runner


def test_default_admin_suite_serializes_the_shared_fixture_api() -> None:
    default_config = (ROOT / "playwright.config.ts").read_text(encoding="utf-8")

    assert "fullyParallel: false" in default_config
    assert "workers: 1" in default_config
    assert "share one mutable fixture API" in default_config
