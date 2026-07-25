from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = ROOT / "infra/db/alembic/versions/0078_provider_source_identity.py"
UP = ROOT / "infra/db/alembic/sql/0078_provider_source_identity.sql"
DOWN = ROOT / "infra/db/alembic/sql/0078_provider_source_identity.down.sql"


def test_provider_source_identity_migration_is_ordered_and_versioned() -> None:
    version = VERSION.read_text(encoding="utf-8")

    assert 'revision = "0078_provider_source_identity"' in version
    assert 'down_revision = "0077_wfc_alert_report_api"' in version
    assert "0078_provider_source_identity.sql" in version
    assert "0078_provider_source_identity.down.sql" in version


def test_kimi_source_upgrade_is_exact_and_downgrade_is_fail_closed() -> None:
    up = UP.read_text(encoding="utf-8")
    down = DOWN.read_text(encoding="utf-8")

    assert "WHEN 'kimi_api' THEN platform = 'kimi'" in up
    assert "'perplexity_api', 'kimi_api', 'anthropic_api'" in up
    assert "'microsoft', 'kimi', 'anthropic'" in up
    assert "geo_source_stratum_v3_json_valid(jsonb)" in up
    assert "cannot remove Kimi source identity" in down
    assert "jsonb_array_elements(protocol.source_strata_snapshot)" in down
    assert "'perplexity_api', 'kimi_api', 'anthropic_api'" not in down
