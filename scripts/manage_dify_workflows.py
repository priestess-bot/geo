#!/usr/bin/env python3
"""Register, canary, activate and inspect GEO-owned Dify Workflow releases."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.knowledge.question_worker import QUESTION_GENERATION_OUTPUT_SCHEMA
from geo_core.model_gateway import build_secret_store_credential_resolver
from geo_core.placements.default_prompts import default_output_schema
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import thaw_mapping
from geo_core.prompts.bootstrap_validation import validate_bootstrap_output
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.rag import RAG_EXTRACTION_OUTPUT_SCHEMA
from geo_core.secrets import SecretVersionHandle
from geo_core.workflow_runtime import (
    DIFY_WORKFLOW_PURPOSES,
    DifyPublishedWorkflowReader,
    DifyWorkflowExecutor,
    PostgresWorkflowRuntimeCatalog,
    PostgresWorkflowRuntimeRepository,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionError,
    WorkflowExecutionRequest,
)
from geo_core.workflow_runtime.contracts import canonical_json_hash


Validator = Callable[[Mapping[str, object]], None]

BOOTSTRAP_CANARY_KINDS = {
    "synthetic_lab.generation": ProgramKind.GENERATION,
    "synthetic_lab.claim_extraction": ProgramKind.CLAIM_EXTRACTION,
    "synthetic_lab.conflict_check": ProgramKind.CONFLICT_CHECK,
    "synthetic_lab.revision": ProgramKind.REVISION,
    "synthetic_lab.style_profile": ProgramKind.STYLE_PROFILE,
    "recommendations.recommendation": ProgramKind.RECOMMENDATION,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url-env",
        default="GEO_DATABASE_URL",
        help="environment variable containing the role-appropriate PostgreSQL URL",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    listing = commands.add_parser("list", help="show all supported runtime cards")
    listing.add_argument("--project-id", required=True)

    register = commands.add_parser("register", help="register one immutable release")
    register.add_argument("--project-id", required=True)
    register.add_argument("--purpose", required=True, choices=sorted(DIFY_WORKFLOW_PURPOSES))
    register.add_argument("--prompt-program-id", required=True)
    register.add_argument("--prompt-release-id", required=True)
    register.add_argument("--app-id", required=True)
    register.add_argument("--workflow-id", required=True)
    register.add_argument("--dsl-file", required=True)
    register.add_argument("--secret-reference-id", required=True)
    register.add_argument("--secret-version", required=True, type=int)
    register.add_argument("--created-by", required=True)
    register.add_argument("--configured-model", default="deepseek-chat")
    register.add_argument("--model-provider", default="langgenius/deepseek/deepseek")
    register.add_argument("--dify-console-url", default="http://127.0.0.1:15000")
    register.add_argument(
        "--dify-state-file", default=".runtime/geo-dify-state.json"
    )

    canary = commands.add_parser(
        "canary", help="run one real provider call and persist its semantic result"
    )
    canary.add_argument("--project-id", required=True)
    canary.add_argument("--release-id", required=True)
    canary.add_argument("--worker-actor-id", required=True)
    canary.add_argument("--master-keyring-file", required=True)
    canary.add_argument("--request-hash-key-file", required=True)
    canary.add_argument("--dify-api-url", default="http://dify-api:5001")
    canary.add_argument("--dify-console-url", default="http://127.0.0.1:15000")
    canary.add_argument(
        "--dify-state-file", default=".runtime/geo-dify-state.json"
    )
    canary.add_argument("--timeout-seconds", type=float, default=180.0)

    activate = commands.add_parser(
        "activate", help="activate a release that has a successful real canary"
    )
    activate.add_argument("--project-id", required=True)
    activate.add_argument("--release-id", required=True)
    activate.add_argument("--activated-by", required=True)
    activate.add_argument("--reason", required=True)

    reconcile = commands.add_parser(
        "reconcile-new-parent",
        help="record Dify run verification and authorize only a new parent Job",
    )
    reconcile.add_argument("--project-id", required=True)
    reconcile.add_argument("--attempt-id", required=True)
    reconcile.add_argument("--authorized-by", required=True)
    reconcile.add_argument(
        "--provider-outcome",
        required=True,
        choices=(
            "not_found",
            "failed_without_output",
            "succeeded_output_unrecoverable",
        ),
    )
    reconcile.add_argument(
        "--provider-run-id",
        help="required unless --provider-outcome=not_found",
    )
    reconcile.add_argument("--evidence-reference", required=True)
    reconcile.add_argument("--reason", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        database_url = _required_env(args.database_url_env)
        project_id = _uuid(args.project_id, "project")
        if args.command == "list":
            cards = PostgresWorkflowRuntimeCatalog(database_url).list_cards(
                project_id=project_id
            )
            _print(
                {
                    "project_id": str(project_id),
                    "items": [_json_value(card.__dict__) for card in cards],
                }
            )
            return 0
        if args.command == "register":
            dsl_path = Path(args.dsl_file).resolve()
            body = dsl_path.read_bytes()
            if not body:
                raise WorkflowContractError("Dify DSL file cannot be empty")
            snapshot = DifyPublishedWorkflowReader(
                base_url=args.dify_console_url,
                state_file=args.dify_state_file,
            ).read(purpose=args.purpose, app_id=args.app_id)
            if snapshot.workflow_id != args.workflow_id:
                raise WorkflowConfigurationError(
                    "published Dify Workflow ID differs from --workflow-id; "
                    "refresh the private state before registration",
                    code="dify_published_workflow_id_mismatch",
                )
            release_id = PostgresWorkflowRuntimeCatalog(database_url).register_release(
                project_id=project_id,
                purpose=args.purpose,
                prompt_program_id=_uuid(args.prompt_program_id, "Prompt Program"),
                prompt_release_id=_uuid(args.prompt_release_id, "Prompt Release"),
                dify_app_id=args.app_id,
                dify_workflow_id=args.workflow_id,
                dsl_hash=hashlib.sha256(body).hexdigest(),
                registered_workflow_hash=snapshot.workflow_hash,
                registered_snapshot_hash=snapshot.snapshot_hash,
                configured_model=args.configured_model,
                model_provider=args.model_provider,
                api_secret_handle=SecretVersionHandle(
                    reference_id=_uuid(args.secret_reference_id, "Secret reference"),
                    project_id=project_id,
                    purpose="workflow_runtime.dify",
                    version=args.secret_version,
                ),
                created_by=_uuid(args.created_by, "creator"),
            )
            _print({"status": "registered", "release_id": str(release_id)})
            return 0
        if args.command == "canary":
            release_id = _uuid(args.release_id, "release")
            store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
            repository = PostgresWorkflowRuntimeRepository(store)
            release = repository.get_release(project_id=project_id, release_id=release_id)
            request, validator = canary_contract(project_id, release.purpose)
            result = DifyWorkflowExecutor(
                repository=repository,
                credential_resolver=build_secret_store_credential_resolver(
                    database_url=database_url,
                    master_keyring_path=args.master_keyring_file,
                    request_hash_key_path=args.request_hash_key_file,
                    worker_actor_id=_uuid(args.worker_actor_id, "worker actor"),
                ),
                base_url=args.dify_api_url,
                timeout_seconds=args.timeout_seconds,
                published_reader=DifyPublishedWorkflowReader(
                    base_url=args.dify_console_url,
                    state_file=args.dify_state_file,
                ),
            ).execute_canary(
                project_id=project_id,
                release_id=release_id,
                request=request,
                validate_output=validator,
            )
            _print(
                {
                    "status": "succeeded",
                    "release_id": str(release_id),
                    "attempt_id": str(result.attempt_id),
                    "dify_run_id": result.dify_run_id,
                    "response_hash": result.response_hash,
                }
            )
            return 0
        if args.command == "activate":
            binding_id = PostgresWorkflowRuntimeCatalog(database_url).activate_release(
                project_id=project_id,
                release_id=_uuid(args.release_id, "release"),
                activated_by=_uuid(args.activated_by, "activator"),
                reason=args.reason,
            )
            _print({"status": "activated", "binding_id": str(binding_id)})
            return 0
        if args.command == "reconcile-new-parent":
            attempt_id = _uuid(args.attempt_id, "attempt")
            token = PostgresWorkflowRuntimeCatalog(
                database_url
            ).authorize_new_parent_after_unknown_outcome(
                project_id=project_id,
                attempt_id=attempt_id,
                authorized_by=_uuid(args.authorized_by, "authorizer"),
                provider_outcome=args.provider_outcome,
                provider_run_id=args.provider_run_id,
                evidence_reference=args.evidence_reference,
                reason=args.reason,
            )
            _print(
                {
                    "status": "new_parent_authorized",
                    "attempt_id": str(attempt_id),
                    "dify_reconciliation_token": token,
                    "old_job_reusable": False,
                    "next_action": (
                        "Submit a new parent Job with a new idempotency/replay identity and "
                        "this one-time token. Never retry or reopen the old Job."
                    ),
                }
            )
            return 0
        raise AssertionError("unreachable command")
    except (OSError, ValueError, psycopg.Error, WorkflowExecutionError) as exc:
        print(f"Dify workflow command failed: {exc}", file=sys.stderr)
        return 1


def canary_contract(project_id: UUID, purpose: str) -> tuple[WorkflowExecutionRequest, Validator]:
    if purpose == "knowledge.question_generation":
        context: Mapping[str, object] = {
            "dimensions": [
                {
                    "dimension_key": "au-geo-awareness",
                    "turn_index": 1,
                    "parent_dimension_key": None,
                }
            ],
            "facts": [
                {
                    "fact_candidate_id": "00000000-0000-4000-8000-000000000101",
                    "statement": "Advinsys provides GEO analytics in Australia.",
                }
            ],
            "entities": [
                {
                    "graph_entity_id": "00000000-0000-4000-8000-000000000102",
                    "entity_type": "Brand",
                    "canonical_name": "Advinsys",
                }
            ],
            "parent_candidates": [],
        }
        system = (
            "Return exactly one object containing only a questions array. Generate exactly one "
            "Australian English question using the field text and "
            "for dimension au-geo-awareness, candidate_id canary-question-1, variant_index 1, "
            "semantic_fingerprint geo analytics australia, supported_fact_ids containing only "
            "00000000-0000-4000-8000-000000000101, supported_entity_ids containing only "
            "00000000-0000-4000-8000-000000000102, and parent_candidate_id null."
        )
        validator = _validate_question_canary
        output_schema = QUESTION_GENERATION_OUTPUT_SCHEMA
    elif purpose == "knowledge.rag_grounding":
        source = "Advinsys provides GEO analytics in Australia."
        context = {
            "adapter_purpose": "geo-knowledge-extraction",
            "source_document": {"document_id": "canary-doc", "content": source},
        }
        system = (
            "Extract only exact source text. Return exactly facts, entities and relations arrays. "
            f"Include one fact whose text and source_quote are exactly: {source}"
        )
        validator = _validate_rag_canary
        output_schema = RAG_EXTRACTION_OUTPUT_SCHEMA
    elif purpose in {"placements.generation", "placements.simulation"}:
        context = {
            "campaign_id": "00000000-0000-4000-8000-000000000201",
            "mode": "canary",
            "approved_fact": "Advinsys provides GEO analytics in Australia.",
            "internal_evidence_ids": [],
            "public_citation_ids": [],
        }
        system = (
            "Return exactly content_json, rendered_text, claims, internal_evidence_refs and "
            "public_citation_refs. content_json must contain empty required_disclosures and "
            "expected_links arrays. rendered_text must be a non-empty Australian English draft. "
            "Use Australian English. Set claims and both reference arrays to empty arrays."
        )
        validator = _validate_placement_canary
        output_schema = default_output_schema()
    elif purpose in BOOTSTRAP_CANARY_KINDS:
        kind = BOOTSTRAP_CANARY_KINDS[purpose]
        spec = default_prompt_bootstrap_spec(kind)
        fixture = next(item for item in spec.fixtures if item.expected_valid)
        context = dict(thaw_mapping(fixture.input_value))
        validation_context = context
        expected = dict(thaw_mapping(fixture.expected_output))
        if kind is ProgramKind.CONFLICT_CHECK:
            claim = _first_mutable_object(context.get("claims"), field="claims")
            claim["text"] = "The placeholder subject does not have the approved synthetic attribute."
            assessment = _first_mutable_object(
                expected.get("assessments"), field="assessments"
            )
            assessment["status"] = "explicit_conflict"
            expected["requires_revision"] = True
        elif kind is ProgramKind.REVISION:
            context["candidate_text"] = (
                "The placeholder subject does not have the approved synthetic attribute."
            )
            context["issue_codes"] = ["explicit_conflict"]
            expected["resolved_issue_codes"] = ["explicit_conflict"]
            expected["revised_text"] = (
                "The placeholder subject has the approved synthetic attribute."
            )
        system = (
            "Return exactly this deterministic JSON object after checking it against the supplied "
            f"context: {json.dumps(expected, ensure_ascii=False, sort_keys=True)}"
        )

        def validator(output: Mapping[str, object]) -> None:
            try:
                validate_bootstrap_output(
                    spec, input_value=validation_context, output=output
                )
            except Exception as exc:
                raise WorkflowContractError(
                    f"{purpose} canary failed its frozen semantics: {exc}",
                    code="dify_canary_semantic_invalid",
                ) from exc
            if kind is ProgramKind.CONFLICT_CHECK:
                assessment = _first_object(output.get("assessments"))
                if (
                    output.get("requires_revision") is not True
                    or assessment is None
                    or assessment.get("status") != "explicit_conflict"
                ):
                    raise WorkflowContractError(
                        "conflict canary did not require revision",
                        code="dify_canary_semantic_invalid",
                    )
            if kind is ProgramKind.REVISION and (
                output.get("resolved_issue_codes") != ["explicit_conflict"]
                or "has the approved synthetic attribute" not in str(output.get("revised_text"))
            ):
                raise WorkflowContractError(
                    "revision canary did not resolve the frozen conflict",
                    code="dify_canary_semantic_invalid",
                )
            if kind is ProgramKind.STYLE_PROFILE and (
                output.get("sample_manifest_hash") != context.get("sample_manifest_hash")
                or output.get("evidence_refs") != ["evidence-style-sample-001"]
            ):
                raise WorkflowContractError(
                    "Style Profile canary did not preserve its approved sample lineage",
                    code="dify_canary_semantic_invalid",
                )
            if kind is ProgramKind.RECOMMENDATION and (
                output.get("recommendation_type") != "experiment"
                or output.get("selected_evidence") != expected.get("selected_evidence")
                or output.get("scope") != context.get("scope")
            ):
                raise WorkflowContractError(
                    "recommendation canary escaped its frozen evidence or scope",
                    code="dify_canary_semantic_invalid",
                )

        output_schema = thaw_mapping(spec.schemas.application_output_schema)
    else:
        raise WorkflowContractError("unsupported Dify canary purpose")
    context = {**context, "task_contract": system}
    request_value = {
        "purpose": purpose,
        "context": context,
        "system_prompt": system,
        "user_prompt": "Execute this fixed GEO release canary using only the supplied context.",
    }
    return (
        WorkflowExecutionRequest(
            project_id=project_id,
            purpose=purpose,
            context=context,
            input_hash=canonical_json_hash(request_value),
            output_schema=output_schema,
            system_prompt=system,
            user_prompt=str(request_value["user_prompt"]),
        ),
        validator,
    )


def _first_object(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, list) or not value or not isinstance(value[0], Mapping):
        return None
    return value[0]


def _first_mutable_object(value: object, *, field: str) -> dict[str, object]:
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise WorkflowContractError(
            f"synthetic canary fixture has invalid {field}",
            code="dify_canary_fixture_invalid",
        )
    return value[0]


def _validate_question_canary(output: Mapping[str, object]) -> None:
    rows = output.get("questions")
    if set(output) != {"questions"} or not isinstance(rows, list) or len(rows) != 1:
        raise WorkflowContractError(
            "question canary must return exactly one question", code="dify_canary_semantic_invalid"
        )
    row = rows[0]
    expected = {
        "candidate_id",
        "dimension_key",
        "variant_index",
        "text",
        "semantic_fingerprint",
        "supported_fact_ids",
        "supported_entity_ids",
        "parent_candidate_id",
    }
    if not isinstance(row, Mapping) or set(row) != expected:
        raise WorkflowContractError(
            "question canary fields are invalid", code="dify_canary_semantic_invalid"
        )
    if (
        row.get("dimension_key") != "au-geo-awareness"
        or row.get("variant_index") != 1
        or not isinstance(row.get("text"), str)
        or not str(row["text"]).strip()
        or row.get("parent_candidate_id") is not None
        or row.get("supported_fact_ids")
        != ["00000000-0000-4000-8000-000000000101"]
    ):
        raise WorkflowContractError(
            "question canary did not preserve its frozen evidence",
            code="dify_canary_semantic_invalid",
        )


def _validate_rag_canary(output: Mapping[str, object]) -> None:
    if set(output) != {"facts", "entities", "relations"}:
        raise WorkflowContractError(
            "RAG canary fields are invalid", code="dify_canary_semantic_invalid"
        )
    facts = output.get("facts")
    expected = "Advinsys provides GEO analytics in Australia."
    if not isinstance(facts, list) or not any(
        isinstance(item, Mapping)
        and item.get("text") == expected
        and item.get("source_quote") == expected
        for item in facts
    ):
        raise WorkflowContractError(
            "RAG canary lost exact source grounding", code="dify_canary_semantic_invalid"
        )
    if not isinstance(output.get("entities"), list) or not isinstance(
        output.get("relations"), list
    ):
        raise WorkflowContractError(
            "RAG canary arrays are invalid", code="dify_canary_semantic_invalid"
        )


def _validate_placement_canary(output: Mapping[str, object]) -> None:
    expected = {
        "content_json",
        "rendered_text",
        "claims",
        "internal_evidence_refs",
        "public_citation_refs",
    }
    content = output.get("content_json")
    if set(output) != expected or not isinstance(content, Mapping):
        raise WorkflowContractError(
            "placement canary fields are invalid", code="dify_canary_semantic_invalid"
        )
    for key in ("required_disclosures", "expected_links"):
        if content.get(key) != []:
            raise WorkflowContractError(
                f"placement canary content_json.{key} must be empty",
                code="dify_canary_semantic_invalid",
            )
    if not isinstance(output.get("rendered_text"), str) or not str(
        output["rendered_text"]
    ).strip():
        raise WorkflowContractError(
            "placement canary rendered text is empty", code="dify_canary_semantic_invalid"
        )
    for key in ("claims", "internal_evidence_refs", "public_citation_refs"):
        if output.get(key) != []:
            raise WorkflowContractError(
                f"placement canary {key} must be empty",
                code="dify_canary_semantic_invalid",
            )


def _uuid(value: str, label: str) -> UUID:
    try:
        parsed = UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"{label} ID must be a UUID") from exc
    if parsed.int == 0:
        raise ValueError(f"{label} ID cannot be zero")
    return parsed


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _print(value: Mapping[str, object]) -> None:
    print(json.dumps(_json_value(value), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
