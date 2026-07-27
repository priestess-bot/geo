from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dify_web_overlay_is_pinned_and_reproducible() -> None:
    builder = (ROOT / "scripts/build_dify_web_overlay.sh").read_text()
    bootstrap = (ROOT / "scripts/bootstrap_dify_runtime.sh").read_text()
    patch = ROOT / "infra/dify/patches/dify-1.16.0-geo-run-input-picker.patch"

    assert 'DIFY_COMMIT="5c6372d2f76d240265b92fd27c16bc772ffcb107"' in builder
    assert "git -C \"${build_root}/dify\" apply --check" in builder
    assert "io.geo.dify.web-overlay-sha" in builder
    assert patch.is_file() and patch.stat().st_size > 0
    assert 'DEFAULT_DIFY_WEB_IMAGE="geo-dify-web:1.16.0-geo"' in bootstrap
    assert "ensure_web_image" in bootstrap


def test_dify_compose_supports_explicit_upstream_web_rollback() -> None:
    compose = (ROOT / "infra/dify/docker-compose.dify.yml").read_text()
    env_example = (ROOT / "infra/dify/.env.example").read_text()

    assert '${GEO_DIFY_WEB_IMAGE:-geo-dify-web:1.16.0-geo}' in compose
    assert "GEO_DIFY_WEB_IMAGE=geo-dify-web:1.16.0-geo" in env_example
    assert "langgenius/dify-web:1.16.0" in env_example


def test_overlay_only_changes_dify_test_run_input_ui() -> None:
    patch = (ROOT / "infra/dify/patches/dify-1.16.0-geo-run-input-picker.patch").read_text()

    changed_paths = {
        line.removeprefix("+++ b/")
        for line in patch.splitlines()
        if line.startswith("+++ b/")
    }
    assert changed_paths == {
        "web/app/components/workflow/panel/__tests__/inputs-panel.spec.tsx",
        "web/app/components/workflow/panel/geo-run-input-picker.tsx",
        "web/app/components/workflow/panel/inputs-panel.tsx",
    }
    assert "geo-job:" in patch
    assert "geo-canary:" in patch
