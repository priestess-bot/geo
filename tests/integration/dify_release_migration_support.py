"""Seed pre-0101 Dify releases without using the current runtime catalog."""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.secrets import SecretVersionHandle
from geo_core.workflow_runtime.contracts import (
    CONTEXT_CONTRACT_VERSION,
    DYNAMIC_JSON_OUTPUT_SCHEMA,
    canonical_json_hash,
)


def seed_legacy_dify_release(
    database_url: str,
    *,
    project_id: UUID,
    purpose: str,
    prompt_program_id: UUID,
    prompt_release_id: UUID,
    dify_app_id: str,
    dify_workflow_id: str,
    dsl_hash: str,
    configured_model: str,
    model_provider: str,
    api_secret_handle: SecretVersionHandle,
    created_by: UUID,
) -> UUID:
    input_schema = {
        "type": "object",
        "x-geo-context-contract": CONTEXT_CONTRACT_VERSION,
    }
    output_schema = dict(DYNAMIC_JSON_OUTPUT_SCHEMA)
    release_id = uuid4()
    with psycopg.connect(database_url) as connection:
        prompt = connection.execute(
            """SELECT release_hash FROM prompt_program_releases
               WHERE id = %s AND project_id = %s AND program_id = %s""",
            (prompt_release_id, project_id, prompt_program_id),
        ).fetchone()
        assert prompt is not None
        version = connection.execute(
            """SELECT COALESCE(MAX(version), 0) + 1
               FROM dify_workflow_releases
               WHERE project_id = %s AND purpose = %s""",
            (project_id, purpose),
        ).fetchone()
        assert version is not None
        release_value = {
            "legacy_test_seed": True,
            "purpose": purpose,
            "app_id": dify_app_id,
            "workflow_id": dify_workflow_id,
            "version": int(version[0]),
        }
        connection.execute(
            """INSERT INTO dify_workflow_releases (
                   id, project_id, purpose, version, prompt_program_id,
                   prompt_release_id, prompt_release_hash, dify_app_id,
                   dify_workflow_id, dsl_hash, context_contract_version,
                   input_schema, input_schema_hash, output_schema, output_schema_hash,
                   configured_model, model_provider, api_secret_reference_id,
                   api_secret_purpose, api_secret_version, release_hash, created_by
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
               )""",
            (
                release_id,
                project_id,
                purpose,
                int(version[0]),
                prompt_program_id,
                prompt_release_id,
                prompt[0],
                dify_app_id,
                dify_workflow_id,
                dsl_hash,
                CONTEXT_CONTRACT_VERSION,
                Jsonb(input_schema),
                canonical_json_hash(input_schema),
                Jsonb(output_schema),
                canonical_json_hash(output_schema),
                configured_model,
                model_provider,
                api_secret_handle.reference_id,
                api_secret_handle.purpose,
                api_secret_handle.version,
                canonical_json_hash(release_value),
                created_by,
            ),
        )
        connection.commit()
    return release_id
