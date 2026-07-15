from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from scripts import provision_initial_owner as provisioner


def _environment() -> dict[str, str]:
    return {
        "GEO_INSTALLER_DATABASE_URL": "postgresql://installer:secret@database.example/geo",
        "GEO_JWT_ISSUER": "https://identity.example.com/",
        "GEO_BOOTSTRAP_TENANT_ID": "10000000-0000-4000-8000-000000000001",
        "GEO_BOOTSTRAP_TENANT_NAME": "Initial Tenant",
        "GEO_BOOTSTRAP_OIDC_ISSUER": "https://identity.example.com/",
        "GEO_BOOTSTRAP_OIDC_SUBJECT": "oidc-owner-subject",
        "GEO_BOOTSTRAP_EMAIL": "owner@example.com",
        "GEO_BOOTSTRAP_DISPLAY_NAME": "Initial Owner",
        "GEO_BOOTSTRAP_PROJECT_ID": "20000000-0000-4000-8000-000000000002",
        "GEO_BOOTSTRAP_PROJECT_NAME": "Initial Project",
    }


def test_environment_contract_accepts_only_matching_oidc_issuer() -> None:
    database_url, config = provisioner.configuration_from_environment(_environment())

    assert database_url.startswith("postgresql://installer:")
    assert config.oidc_issuer == _environment()["GEO_JWT_ISSUER"]
    assert config.email == "owner@example.com"

    mismatch = {**_environment(), "GEO_BOOTSTRAP_OIDC_ISSUER": "https://other.example/"}
    with pytest.raises(
        provisioner.InitialOwnerProvisionError,
        match="bootstrap_oidc_issuer_mismatch",
    ):
        provisioner.configuration_from_environment(mismatch)


def test_database_url_file_is_exclusive_and_not_part_of_business_config(tmp_path: Path) -> None:
    secret = tmp_path / "installer-database-url"
    secret.write_text("postgresql://installer:secret@database.example/geo\n", encoding="utf-8")
    file_environment = _environment()
    file_environment.pop("GEO_INSTALLER_DATABASE_URL")
    file_environment["GEO_INSTALLER_DATABASE_URL_FILE"] = str(secret)

    database_url, config = provisioner.configuration_from_environment(file_environment)

    assert database_url.endswith("/geo")
    assert not hasattr(config, "database_url")
    with pytest.raises(
        provisioner.InitialOwnerProvisionError,
        match="bootstrap_database_configuration_invalid",
    ):
        provisioner.configuration_from_environment(
            {**file_environment, "GEO_INSTALLER_DATABASE_URL": database_url}
        )


def test_exact_replay_validation_rejects_any_changed_field() -> None:
    _, config = provisioner.configuration_from_environment(_environment())
    identity_id = UUID("30000000-0000-4000-8000-000000000003")
    tenant = {"name": config.tenant_name, "status": "active"}
    identity = {
        "id": identity_id,
        "issuer": config.oidc_issuer,
        "subject": config.oidc_subject,
        "email": config.email,
        "display_name": config.display_name,
        "status": "active",
    }
    project = {
        "tenant_id": config.tenant_id,
        "name": config.project_name,
        "status": "active",
    }
    membership = {
        "tenant_id": config.tenant_id,
        "project_id": config.project_id,
        "identity_id": identity_id,
        "role": "owner",
        "status": "active",
    }

    assert str(
        provisioner._validate_exact_replay(
            config=config,
            tenant=tenant,
            identity=identity,
            project=project,
            membership=membership,
        )
    ) == str(identity_id)
    with pytest.raises(
        provisioner.InitialOwnerProvisionError,
        match="bootstrap_existing_state_conflict",
    ):
        provisioner._validate_exact_replay(
            config=replace(config, project_name="Changed"),
            tenant=tenant,
            identity=identity,
            project=project,
            membership=membership,
        )
