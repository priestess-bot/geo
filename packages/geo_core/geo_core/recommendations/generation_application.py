"""Pure application service for governed Recommendation generation Jobs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import re
from uuid import UUID, uuid4

from geo_core.model_gateway.application_support import ExecuteModelCall
from geo_core.model_gateway.contracts import (
    ModelCaptureMethod,
    ModelGatewayError,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.model_gateway.ports import ModelCallAttemptKind
from geo_core.model_gateway.releases import ModelRoute
from geo_core.recommendations.errors import RecommendationRuleViolation
from geo_core.recommendations.generation_contracts import (
    FrozenPromptBinding,
    GenerationExecution,
    GenerationJobOwnership,
    GenerationJobStatus,
    RecommendationGenerationJob,
    RecommendationGenerationOutputError,
    RecommendationGenerationResult,
    RecommendationGenerationSpec,
    RecommendationGenerationStale,
    ResolvedGenerationPrompt,
    canonical_hash,
    idempotency_hash,
)
from geo_core.recommendations.generation_ports import (
    ARBITER_APPLICATION_OUTPUT_SCHEMA,
    ARBITER_OUTPUT_SCHEMA,
    RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
    RECOMMENDATION_OUTPUT_SCHEMA,
    ModelGatewayApplicationPort,
    ParsedRecommendationOutput,
    RecommendationFactResolverPort,
    RecommendationGenerationRepositoryPort,
    RecommendationPromptResolverPort,
    parse_recommendation_output,
    require_arbiter_acceptance,
    structured_arbiter_input,
    structured_generation_input,
    validated_recommendation_evidence_refs,
)
from geo_core.recommendations.generation_results import (
    build_insufficient_result,
    build_model_result,
)


class RecommendationGenerationApplication:
    def __init__(
        self,
        *,
        repository: RecommendationGenerationRepositoryPort,
        prompts: RecommendationPromptResolverPort,
        facts: RecommendationFactResolverPort,
        model_gateway: ModelGatewayApplicationPort,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._prompts = prompts
        self._facts = facts
        self._model_gateway = model_gateway
        self._id_factory = id_factory
        self._clock = clock

    def enqueue(
        self,
        spec: RecommendationGenerationSpec,
        *,
        idempotency_key: str,
    ) -> GenerationExecution:
        job, replayed = self._repository.create_job(
            job_id=self._id_factory(),
            spec=spec,
            idempotency_key_hash=idempotency_hash(idempotency_key),
        )
        return GenerationExecution(
            job, self._repository.result(project_id=spec.project_id, job_id=job.id), replayed
        )

    def claim(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        worker_id: str,
        lease_for: timedelta,
    ) -> RecommendationGenerationJob:
        return self._repository.claim_job(
            project_id=project_id,
            job_id=job_id,
            worker_id=worker_id,
            now=self._clock(),
            lease_for=lease_for,
        )

    def get(self, *, project_id: UUID, job_id: UUID) -> GenerationExecution:
        job = self._repository.get_job(project_id=project_id, job_id=job_id)
        return GenerationExecution(
            job, self._repository.result(project_id=project_id, job_id=job_id)
        )

    def cancel(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> RecommendationGenerationJob:
        return self._repository.request_cancel(
            project_id=project_id,
            job_id=job_id,
            expected_version=expected_version,
            idempotency_key_hash=(
                idempotency_hash(idempotency_key) if idempotency_key is not None else None
            ),
        )

    def run(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        ownership: GenerationJobOwnership,
    ) -> GenerationExecution:
        now = self._clock()
        job = self._repository.require_owned(
            project_id=project_id,
            job_id=job_id,
            ownership=ownership,
            now=now,
        )
        if job.cancel_requested:
            return self._terminal(job, ownership, GenerationJobStatus.CANCELLED, None, "cancelled")
        if job.spec.valid_until <= now:
            return self._terminal(job, ownership, GenerationJobStatus.FAILED, None, "expired_spec")
        structured_input = structured_generation_input(job.spec.evidence)
        insufficiency = job.spec.evidence.insufficiency_reasons(
            minimum_real_observations=job.spec.minimum_real_observations
        )
        try:
            primary_prompt = self._resolve_exact(
                job.spec.prompt_binding,
                route=job.spec.route,
                configured_model=job.spec.configured_model,
                model_policy=job.spec.model_policy,
                capture_method=job.spec.capture_method,
                search_mode=job.spec.search_mode,
                structured_input=structured_input,
                output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
                application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
            )
            self._assert_facts_current(job.spec)
            if insufficiency:
                result = self._insufficient_result(job.spec, insufficiency)
                self._assert_terminal_inputs(job.spec, structured_input, primary_prompt)
                return self._succeed_or_cancel(job, ownership, result)

            primary_call = self._execute_model(
                job,
                ownership,
                prompt=primary_prompt,
                role="generation",
            )
            parsed = parse_recommendation_output(
                primary_call.output,
                evidence=job.spec.evidence,
            )
            call_results = [primary_call]
            prompt_bindings = [primary_prompt.binding]
            if job.spec.arbiter_binding is not None:
                assert job.spec.arbiter_route is not None
                assert job.spec.arbiter_configured_model is not None
                assert job.spec.arbiter_model_policy is not None
                assert job.spec.arbiter_capture_method is not None
                arbiter_input = structured_arbiter_input(
                    primary_call.output,
                    evidence=job.spec.evidence,
                )
                arbiter_prompt = self._resolve_exact(
                    job.spec.arbiter_binding,
                    route=job.spec.arbiter_route,
                    configured_model=job.spec.arbiter_configured_model,
                    model_policy=job.spec.arbiter_model_policy,
                    capture_method=job.spec.arbiter_capture_method,
                    search_mode=job.spec.arbiter_search_mode,
                    structured_input=arbiter_input,
                    output_schema=ARBITER_OUTPUT_SCHEMA,
                    application_output_schema=ARBITER_APPLICATION_OUTPUT_SCHEMA,
                )
                arbiter_call = self._execute_model(
                    job,
                    ownership,
                    prompt=arbiter_prompt,
                    role="arbiter",
                )
                require_arbiter_acceptance(
                    arbiter_call.output,
                    evidence=job.spec.evidence,
                    candidate_id=canonical_hash(primary_call.output),
                    evidence_refs=validated_recommendation_evidence_refs(
                        primary_call.output,
                        evidence=job.spec.evidence,
                    ),
                )
                current_arbiter = self._resolve_exact(
                    job.spec.arbiter_binding,
                    route=job.spec.arbiter_route,
                    configured_model=job.spec.arbiter_configured_model,
                    model_policy=job.spec.arbiter_model_policy,
                    capture_method=job.spec.arbiter_capture_method,
                    search_mode=job.spec.arbiter_search_mode,
                    structured_input=arbiter_input,
                    output_schema=ARBITER_OUTPUT_SCHEMA,
                    application_output_schema=ARBITER_APPLICATION_OUTPUT_SCHEMA,
                )
                if current_arbiter.prompt_bundle_hash != arbiter_prompt.prompt_bundle_hash:
                    raise RecommendationGenerationStale(
                        "arbiter Prompt changed before terminal write"
                    )
                call_results.append(arbiter_call)
                prompt_bindings.append(arbiter_prompt.binding)
            self._assert_terminal_inputs(job.spec, structured_input, primary_prompt)
            result = self._model_result(job.spec, parsed, call_results, prompt_bindings)
            return self._succeed_or_cancel(job, ownership, result)
        except RecommendationGenerationStale:
            return self._terminal(
                job,
                ownership,
                GenerationJobStatus.REJECTED_STALE_INPUT,
                None,
                "stale_prompt_or_fact",
            )
        except (
            RecommendationGenerationOutputError,
            RecommendationRuleViolation,
            ModelGatewayError,
        ) as error:
            return self._terminal(
                job,
                ownership,
                GenerationJobStatus.FAILED,
                None,
                _error_code(error),
            )

    def _execute_model(
        self,
        job: RecommendationGenerationJob,
        ownership: GenerationJobOwnership,
        *,
        prompt: ResolvedGenerationPrompt,
        role: str,
    ) -> ModelGatewayResult:
        reserved = self._repository.reserve_model_call(
            project_id=job.spec.project_id,
            job_id=job.id,
            ownership=ownership,
            now=self._clock(),
        )
        request = ModelGatewayRequest(
            messages=prompt.messages,
            configured_model=prompt.configured_model,
            prompt_bundle_hash=prompt.prompt_bundle_hash,
            project_id=job.spec.project_id,
            purpose=prompt.binding.purpose,
            temperature=0,
            max_output_tokens=4096,
            output_schema=prompt.output_schema,
            application_output_schema=prompt.application_output_schema,
            search_mode=prompt.search_mode,
            deadline_at=reserved.lease_expires_at,
            idempotency_key=f"recommendation:{job.id}:{role}:{job.input_hash}",
            capture_method=prompt.capture_method,
        )
        execution = self._model_gateway.execute(
            ExecuteModelCall(
                project_id=job.spec.project_id,
                job_id=job.id,
                expected_job_version=reserved.version,
                lease_token=ownership.lease_id,
                fencing_generation=ownership.fencing_token,
                runtime_manifest_id=(
                    job.spec.runtime_manifest_id
                    if role == "generation"
                    else _required_uuid(job.spec.arbiter_runtime_manifest_id)
                ),
                runtime_manifest_hash=(
                    job.spec.runtime_manifest_hash
                    if role == "generation"
                    else _required_text(job.spec.arbiter_runtime_manifest_hash)
                ),
                runtime_option_id=(
                    job.spec.runtime_option_id
                    if role == "generation"
                    else _required_uuid(job.spec.arbiter_runtime_option_id)
                ),
                runtime_option_hash=(
                    job.spec.runtime_option_hash
                    if role == "generation"
                    else _required_text(job.spec.arbiter_runtime_option_hash)
                ),
                route=prompt.route,
                prompt_binding_id=prompt.binding.binding_id,
                prompt_release_id=prompt.binding.release_id,
                prompt_release_hash=prompt.binding.release_hash,
                request=request,
                attempt_kind=ModelCallAttemptKind.INITIAL,
                attempt_idempotency_key=request.idempotency_key or "",
            ),
            policy=prompt.policy,
        )
        if execution.result is None:
            raise RecommendationGenerationOutputError("model output is unavailable or invalid JSON")
        return execution.result

    def _resolve_exact(
        self,
        binding: FrozenPromptBinding,
        *,
        route: ModelRoute,
        configured_model: str,
        model_policy: ModelPolicy,
        capture_method: ModelCaptureMethod,
        search_mode: str | None,
        structured_input: Mapping[str, object],
        output_schema: Mapping[str, object],
        application_output_schema: Mapping[str, object],
    ) -> ResolvedGenerationPrompt:
        try:
            resolved = self._prompts.resolve(
                binding=binding,
                route=route,
                configured_model=configured_model,
                model_policy=model_policy,
                capture_method=capture_method,
                search_mode=search_mode,
                structured_input=structured_input,
                output_schema=output_schema,
                application_output_schema=application_output_schema,
            )
        except Exception as error:
            raise RecommendationGenerationStale(
                "Prompt resolver rejected frozen binding"
            ) from error
        if (
            resolved.binding != binding
            or resolved.route != route
            or resolved.configured_model != configured_model
            or resolved.policy != model_policy
            or resolved.capture_method is not capture_method
            or resolved.search_mode != search_mode
            or resolved.structured_input_hash != canonical_hash(structured_input)
            or canonical_hash(resolved.output_schema) != canonical_hash(output_schema)
            or canonical_hash(resolved.application_output_schema)
            != canonical_hash(application_output_schema)
        ):
            raise RecommendationGenerationStale("resolved Prompt/Model identity changed")
        return resolved

    def _assert_facts_current(self, spec: RecommendationGenerationSpec) -> None:
        try:
            current = self._facts.current_facts(
                project_id=spec.project_id,
                frozen_facts=spec.evidence.facts,
            )
        except Exception as error:
            raise RecommendationGenerationStale("Fact resolver rejected frozen Facts") from error
        if tuple(item.canonical_value() for item in current) != tuple(
            item.canonical_value() for item in spec.evidence.facts
        ) or not all(item.current_and_valid for item in current):
            raise RecommendationGenerationStale("frozen Fact identity or status changed")

    def _assert_terminal_inputs(
        self,
        spec: RecommendationGenerationSpec,
        structured_input: Mapping[str, object],
        initial_prompt: ResolvedGenerationPrompt,
    ) -> None:
        self._assert_facts_current(spec)
        current = self._resolve_exact(
            spec.prompt_binding,
            route=spec.route,
            configured_model=spec.configured_model,
            model_policy=spec.model_policy,
            capture_method=spec.capture_method,
            search_mode=spec.search_mode,
            structured_input=structured_input,
            output_schema=RECOMMENDATION_OUTPUT_SCHEMA,
            application_output_schema=RECOMMENDATION_APPLICATION_OUTPUT_SCHEMA,
        )
        if current.prompt_bundle_hash != initial_prompt.prompt_bundle_hash:
            raise RecommendationGenerationStale("Prompt bundle changed before terminal write")

    def _insufficient_result(
        self,
        spec: RecommendationGenerationSpec,
        reasons: tuple[str, ...],
    ) -> RecommendationGenerationResult:
        return build_insufficient_result(
            spec,
            reasons,
            recommendation_id=self._id_factory(),
            created_at=self._clock(),
        )

    def _model_result(
        self,
        spec: RecommendationGenerationSpec,
        parsed: ParsedRecommendationOutput,
        calls: list[ModelGatewayResult],
        prompt_bindings: list[FrozenPromptBinding],
    ) -> RecommendationGenerationResult:
        return build_model_result(
            spec,
            parsed,
            tuple(calls),
            tuple(prompt_bindings),
            recommendation_id=self._id_factory(),
            created_at=self._clock(),
        )

    def _succeed_or_cancel(
        self,
        job: RecommendationGenerationJob,
        ownership: GenerationJobOwnership,
        result: RecommendationGenerationResult,
    ) -> GenerationExecution:
        current = self._repository.require_owned(
            project_id=job.spec.project_id,
            job_id=job.id,
            ownership=ownership,
            now=self._clock(),
        )
        if current.cancel_requested:
            return self._terminal(job, ownership, GenerationJobStatus.CANCELLED, None, "cancelled")
        return self._terminal(job, ownership, GenerationJobStatus.SUCCEEDED, result, None)

    def _terminal(
        self,
        job: RecommendationGenerationJob,
        ownership: GenerationJobOwnership,
        status: GenerationJobStatus,
        result: RecommendationGenerationResult | None,
        error_code: str | None,
    ) -> GenerationExecution:
        terminal = self._repository.finish_job(
            project_id=job.spec.project_id,
            job_id=job.id,
            ownership=ownership,
            now=self._clock(),
            status=status,
            expected_input_hash=job.input_hash,
            result=result,
            error_code=error_code,
        )
        return GenerationExecution(terminal, result)


def _error_code(error: Exception) -> str:
    return re.sub(r"[^a-z0-9]+", "_", type(error).__name__.lower()).strip("_")[:100]


def _required_uuid(value: UUID | None) -> UUID:
    if value is None:
        raise RecommendationGenerationStale("arbiter runtime UUID lineage is unavailable")
    return value


def _required_text(value: str | None) -> str:
    if value is None:
        raise RecommendationGenerationStale("arbiter runtime hash lineage is unavailable")
    return value
