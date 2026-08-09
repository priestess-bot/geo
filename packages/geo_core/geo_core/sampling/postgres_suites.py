"""Fenced PostgreSQL storage for frozen Sampling Suite inputs and Suites."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import UUID, uuid5

import psycopg
from psycopg.types.json import Jsonb

from geo_core.project_scope import set_project_scope
from geo_core.sampling.contracts import (
    CaptureMethod,
    LocationControl,
    SamplingConflict,
    SamplingNotFound,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
)


SAMPLING_SUITE_INPUT_NAMESPACE = UUID("e319bdf4-c4e0-5262-a43e-d3ca20ba9d09")


class PostgresSamplingSuiteError(SamplingConflict):
    """PostgreSQL rejected a frozen Sampling Suite input or Suite command."""


@dataclass(frozen=True)
class PersistentSamplingSuiteInput:
    """Approved, immutable server-resolved source for one Sampling Suite."""

    id: UUID
    project_id: UUID
    option_key: str
    display_name: str
    question_set_id: UUID
    question_set_version: str
    question_set_hash: str
    questions: tuple[SamplingQuestion, ...]
    adapter_release_id: UUID
    adapter_release_hash: str
    model_release_id: UUID
    model_release_hash: str
    route_policy_id: UUID
    route_policy_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    source_stratum: SamplingSourceStratum
    frozen_at: datetime
    option_hash: str = field(init=False)

    def __post_init__(self) -> None:
        option_key = self.option_key.strip()
        display_name = self.display_name.strip()
        if not option_key or not display_name:
            raise PostgresSamplingSuiteError("Sampling Suite input labels are required")
        if not self.questions:
            raise PostgresSamplingSuiteError("Sampling Suite input requires questions")
        if len({item.question_id for item in self.questions}) != len(self.questions):
            raise PostgresSamplingSuiteError("Sampling Suite input questions must be unique")
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise PostgresSamplingSuiteError("Sampling Suite input frozen_at must be timezone-aware")
        object.__setattr__(self, "option_key", option_key)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "questions", tuple(sorted(self.questions)))
        object.__setattr__(self, "option_hash", _canonical_utf8_hash(self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "option_key": self.option_key,
            "display_name": self.display_name,
            "question_set_id": str(self.question_set_id),
            "question_set_version": self.question_set_version,
            "question_set_hash": self.question_set_hash,
            "questions": [
                {
                    "question_id": item.question_id,
                    "question_version": item.question_version,
                    "text_hash": item.text_hash,
                }
                for item in self.questions
            ],
            "adapter_release_id": str(self.adapter_release_id),
            "adapter_release_hash": self.adapter_release_hash,
            "model_release_id": str(self.model_release_id),
            "model_release_hash": self.model_release_hash,
            "route_policy_id": str(self.route_policy_id),
            "route_policy_hash": self.route_policy_hash,
            "runtime_manifest_id": str(self.runtime_manifest_id),
            "runtime_manifest_hash": self.runtime_manifest_hash,
            "runtime_option_id": str(self.runtime_option_id),
            "runtime_option_hash": self.runtime_option_hash,
            "admission_policy_id": str(self.admission_policy_id),
            "admission_policy_hash": self.admission_policy_hash,
            "source_stratum": self.source_stratum.canonical_value(),
        }


class PostgresSamplingSuiteRepository:
    """Resolve frozen inputs and create Suites only through Project-scoped RPCs."""

    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def register_input(
        self,
        input_option: PersistentSamplingSuiteInput,
        *,
        idempotency_key: str,
    ) -> PersistentSamplingSuiteInput:
        option_id = _input_id(input_option.project_id, input_option.option_key)
        if input_option.id != option_id:
            raise PostgresSamplingSuiteError("Sampling Suite input id is not deterministic")
        command_hash = _hash(
            {
                "operation": "register",
                "option_id": str(option_id),
                "option_hash": input_option.option_hash,
            }
        )
        return self._call_input(
            project_id=input_option.project_id,
            statement="""SELECT * FROM geo_register_workflow_c_sampling_suite_input(
                           %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                       )""",
            parameters=(
                input_option.project_id,
                option_id,
                input_option.option_key,
                input_option.option_hash,
                _hash_key(idempotency_key),
                command_hash,
                Jsonb(input_option.payload()),
                input_option.frozen_at,
            ),
        )

    def resolve_input(
        self, *, project_id: UUID, option_key: str
    ) -> PersistentSamplingSuiteInput:
        return self._read_input(project_id=project_id, option_key=option_key, required=True)

    def list_inputs(self, *, project_id: UUID) -> tuple[PersistentSamplingSuiteInput, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_suite_input_options
                   WHERE project_id = %s AND status = 'approved'
                   ORDER BY display_name, option_key""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingSuiteError("Sampling Suite inputs could not be listed") from error
        finally:
            connection.close()
        return tuple(_input(_mapping(row)) for row in rows)

    def create_suite(
        self,
        suite: SamplingSuite,
        *,
        input_option: PersistentSamplingSuiteInput,
        idempotency_key: str,
        selected_question_set_item_ids: tuple[str, ...] | None = None,
    ) -> SamplingSuite:
        if suite.project_id != input_option.project_id:
            raise PostgresSamplingSuiteError("Sampling Suite input Project differs")
        command_value: dict[str, object] = {
            "operation": "create",
            "suite_id": str(suite.id),
            "suite_hash": suite.suite_hash,
            "input_option_hash": input_option.option_hash,
            "frozen_by": suite.frozen_by,
        }
        payload = {
            "schema_version": 1,
            "suite": suite.canonical_value(),
            "frozen_by": suite.frozen_by,
            "frozen_at": suite.frozen_at.isoformat(),
        }
        if selected_question_set_item_ids is not None:
            selected = tuple(selected_question_set_item_ids)
            if len(selected) != 10 or len(set(selected)) != 10:
                raise PostgresSamplingSuiteError(
                    "Sampling Suite selection must contain 10 unique QuestionSet item IDs"
                )
            if set(selected) != {question.question_id for question in suite.questions}:
                raise PostgresSamplingSuiteError(
                    "Sampling Suite selection differs from its frozen questions"
                )
            payload["question_set_item_ids"] = list(selected)
            command_value["question_set_item_ids"] = list(selected)
        # Keep the pre-0126 command shape byte-for-byte stable for legacy Suite
        # replays. The selection key is part of the command only when the
        # caller explicitly opts into the ten-question pilot contract.
        command_hash = _hash(command_value)
        return self._call_suite(
            project_id=suite.project_id,
            statement="""SELECT * FROM geo_create_workflow_c_sampling_suite(
                           %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                       )""",
            parameters=(
                suite.project_id,
                suite.id,
                _hash_key(idempotency_key),
                command_hash,
                input_option.id,
                input_option.option_hash,
                suite.suite_hash,
                Jsonb(payload),
                suite.frozen_at,
            ),
        )

    def get_suite(self, *, project_id: UUID, suite_id: UUID) -> SamplingSuite:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM workflow_c_sampling_suites
                   WHERE project_id = %s AND id = %s""",
                (project_id, suite_id),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingSuiteError("Sampling Suite could not be read") from error
        finally:
            connection.close()
        if row is None:
            raise SamplingNotFound("Sampling Suite does not exist")
        return _suite(_mapping(row))

    def list_suites(self, *, project_id: UUID) -> tuple[SamplingSuite, ...]:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            rows = connection.execute(
                """SELECT * FROM workflow_c_sampling_suites
                   WHERE project_id = %s ORDER BY frozen_at DESC, id DESC""",
                (project_id,),
            ).fetchall()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingSuiteError("Sampling Suites could not be listed") from error
        finally:
            connection.close()
        return tuple(_suite(_mapping(row)) for row in rows)

    def _read_input(
        self, *, project_id: UUID, option_key: str, required: bool
    ) -> PersistentSamplingSuiteInput:
        connection = self._connect()
        try:
            set_project_scope(connection, project_id)
            row = connection.execute(
                """SELECT * FROM workflow_c_sampling_suite_input_options
                   WHERE project_id = %s AND option_key = %s AND status = 'approved'""",
                (project_id, option_key),
            ).fetchone()
            connection.rollback()
        except psycopg.Error as error:
            connection.rollback()
            raise PostgresSamplingSuiteError("Sampling Suite input could not be read") from error
        finally:
            connection.close()
        if row is None and required:
            raise SamplingNotFound("approved Sampling Suite input does not exist")
        assert row is not None
        return _input(_mapping(row))

    def _call_input(
        self, *, project_id: UUID, statement: str, parameters: tuple[object, ...]
    ) -> PersistentSamplingSuiteInput:
        return _call(self._connect, project_id, statement, parameters, _input)

    def _call_suite(
        self, *, project_id: UUID, statement: str, parameters: tuple[object, ...]
    ) -> SamplingSuite:
        return _call(self._connect, project_id, statement, parameters, _suite)


def _call(
    connect: Callable[[], Any],
    project_id: UUID,
    statement: str,
    parameters: tuple[object, ...],
    parser: Callable[[Mapping[str, object]], Any],
) -> Any:
    connection = connect()
    try:
        set_project_scope(connection, project_id)
        row = connection.execute(statement, parameters).fetchone()
        if row is None:
            raise PostgresSamplingSuiteError("Sampling Suite command did not return a result")
        result = parser(_mapping(row))
        connection.commit()
        return result
    except PostgresSamplingSuiteError:
        connection.rollback()
        raise
    except psycopg.Error as error:
        connection.rollback()
        detail = getattr(error.diag, "message_primary", "") or ""
        if detail.startswith(("Sampling Suite ", "Provider Sampling Suite ")):
            raise PostgresSamplingSuiteError(detail) from error
        raise PostgresSamplingSuiteError("PostgreSQL rejected the Sampling Suite command") from error
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _input(row: Mapping[str, object]) -> PersistentSamplingSuiteInput:
    payload = _json(row, "payload")
    expected = {
        "schema_version",
        "option_key",
        "display_name",
        "question_set_id",
        "question_set_version",
        "question_set_hash",
        "questions",
        "adapter_release_id",
        "adapter_release_hash",
        "model_release_id",
        "model_release_hash",
        "route_policy_id",
        "route_policy_hash",
        "runtime_manifest_id",
        "runtime_manifest_hash",
        "runtime_option_id",
        "runtime_option_hash",
        "admission_policy_id",
        "admission_policy_hash",
        "source_stratum",
    }
    if set(payload) != expected or payload.get("schema_version") != 1:
        raise PostgresSamplingSuiteError("Sampling Suite input payload schema is invalid")
    result = PersistentSamplingSuiteInput(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        option_key=_text(payload, "option_key"),
        display_name=_text(payload, "display_name"),
        question_set_id=_uuid(payload, "question_set_id"),
        question_set_version=_text(payload, "question_set_version"),
        question_set_hash=_text(payload, "question_set_hash"),
        questions=_questions(payload),
        adapter_release_id=_uuid(payload, "adapter_release_id"),
        adapter_release_hash=_text(payload, "adapter_release_hash"),
        model_release_id=_uuid(payload, "model_release_id"),
        model_release_hash=_text(payload, "model_release_hash"),
        route_policy_id=_uuid(payload, "route_policy_id"),
        route_policy_hash=_text(payload, "route_policy_hash"),
        runtime_manifest_id=_uuid(payload, "runtime_manifest_id"),
        runtime_manifest_hash=_text(payload, "runtime_manifest_hash"),
        runtime_option_id=_uuid(payload, "runtime_option_id"),
        runtime_option_hash=_text(payload, "runtime_option_hash"),
        admission_policy_id=_uuid(payload, "admission_policy_id"),
        admission_policy_hash=_text(payload, "admission_policy_hash"),
        source_stratum=_source(payload),
        frozen_at=_datetime(row, "frozen_at"),
    )
    if result.id != _input_id(result.project_id, result.option_key):
        raise PostgresSamplingSuiteError("Sampling Suite input identity is corrupt")
    if result.option_hash != _text(row, "option_hash"):
        raise PostgresSamplingSuiteError("Sampling Suite input hash is corrupt")
    if result.admission_policy_id != _uuid(row, "admission_policy_id") or (
        result.admission_policy_hash != _text(row, "admission_policy_hash")
    ):
        raise PostgresSamplingSuiteError("Sampling Suite input admission lineage is corrupt")
    return result


def _suite(row: Mapping[str, object]) -> SamplingSuite:
    payload = _json(row, "payload")
    expected_payload_keys = {"schema_version", "suite", "frozen_by", "frozen_at"}
    if (
        not set(payload).issubset(expected_payload_keys | {"question_set_item_ids"})
        or (not expected_payload_keys.issubset(payload))
        or (payload.get("schema_version") != 1)
    ):
        raise PostgresSamplingSuiteError("Sampling Suite payload schema is invalid")
    value = _mapping(payload.get("suite"))
    if "question_set_item_ids" in payload:
        selected = payload.get("question_set_item_ids")
        if (
            not isinstance(selected, list)
            or len(selected) != 10
            or any(not isinstance(item, str) or not item.strip() for item in selected)
            or len(set(selected)) != 10
        ):
            raise PostgresSamplingSuiteError("Sampling Suite question selection is invalid")
        raw_questions = value.get("questions")
        if not isinstance(raw_questions, list) or {
            _text(_mapping(item), "question_id") for item in raw_questions
        } != set(selected):
            raise PostgresSamplingSuiteError("Sampling Suite question selection is corrupt")
    suite = SamplingSuite(
        id=_uuid(row, "id"),
        project_id=_uuid(row, "project_id"),
        question_set_id=_uuid(value, "question_set_id"),
        question_set_version=_text(value, "question_set_version"),
        question_set_hash=_text(value, "question_set_hash"),
        adapter_release_id=_uuid(value, "adapter_release_id"),
        adapter_release_hash=_text(value, "adapter_release_hash"),
        model_release_id=_uuid(value, "model_release_id"),
        model_release_hash=_text(value, "model_release_hash"),
        route_policy_id=_uuid(value, "route_policy_id"),
        route_policy_hash=_text(value, "route_policy_hash"),
        runtime_manifest_id=_uuid(value, "runtime_manifest_id"),
        runtime_manifest_hash=_text(value, "runtime_manifest_hash"),
        runtime_option_id=_uuid(value, "runtime_option_id"),
        runtime_option_hash=_text(value, "runtime_option_hash"),
        admission_policy_id=_uuid(value, "admission_policy_id"),
        admission_policy_hash=_text(value, "admission_policy_hash"),
        questions=_questions(value),
        source_stratum=_source(value),
        repetitions=_integer(value, "repetitions"),
        statistics_method_version=_text(value, "statistics_method_version"),
        max_planned_tasks=_integer(value, "max_planned_tasks"),
        max_daily_tasks=_integer(value, "max_daily_tasks"),
        minimum_request_interval_seconds=_integer(value, "minimum_request_interval_seconds"),
        max_concurrency=_integer(value, "max_concurrency"),
        frozen_by=_text(payload, "frozen_by"),
        frozen_at=_datetime(row, "frozen_at"),
    )
    if suite.suite_hash != _text(row, "suite_hash"):
        raise PostgresSamplingSuiteError("Sampling Suite hash is corrupt")
    if suite.admission_policy_id != _uuid(row, "admission_policy_id") or (
        suite.admission_policy_hash != _text(row, "admission_policy_hash")
    ):
        raise PostgresSamplingSuiteError("Sampling Suite admission lineage is corrupt")
    if suite.source_stratum.stratum_hash != _text(row, "source_stratum_hash"):
        raise PostgresSamplingSuiteError("Sampling Suite source stratum hash is corrupt")
    return suite


def _questions(value: Mapping[str, object]) -> tuple[SamplingQuestion, ...]:
    raw = value.get("questions")
    if not isinstance(raw, list):
        raise PostgresSamplingSuiteError("Sampling Suite questions are invalid")
    return tuple(
        SamplingQuestion(
            question_id=_text(_mapping(item), "question_id"),
            question_version=_text(_mapping(item), "question_version"),
            text_hash=_text(_mapping(item), "text_hash"),
        )
        for item in raw
    )


def _source(value: Mapping[str, object]) -> SamplingSourceStratum:
    return sampling_source_stratum_from_value(value.get("source_stratum"))


def sampling_source_stratum_from_value(value: object) -> SamplingSourceStratum:
    """Decode one persisted Suite source with the canonical Sampling contract."""
    source = _mapping(value)
    try:
        return SamplingSourceStratum(
            platform=_text(source, "platform"),
            surface=_text(source, "surface"),
            configured_model=_text(source, "configured_model"),
            reported_model=_text(source, "reported_model"),
            capture_method=CaptureMethod(_text(source, "capture_method")),
            adapter_release=_text(source, "adapter_release"),
            locale=_text(source, "locale"),
            region=_text(source, "region"),
            language=_text(source, "language"),
            search_mode=_text(source, "search_mode"),
            account_cohort=_text(source, "account_cohort"),
            egress_policy_category=_text(source, "egress_policy_category"),
            location_control=LocationControl(_text(source, "location_control")),
            location_evidence_hash=_text(source, "location_evidence_hash"),
            requested_country=_nullable_text(source, "requested_country"),
            requested_region=_nullable_text(source, "requested_region"),
            requested_locale=_text(source, "requested_locale"),
            requested_language=_text(source, "requested_language"),
            effective_country=_nullable_text(source, "effective_country"),
            effective_region=_nullable_text(source, "effective_region"),
            effective_locale=_nullable_text(source, "effective_locale"),
            effective_language=_nullable_text(source, "effective_language"),
        )
    except ValueError as error:
        raise PostgresSamplingSuiteError("Sampling Suite source stratum is invalid") from error


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PostgresSamplingSuiteError("Sampling Suite row mapping is invalid")
    return value


def _json(row: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _mapping(row.get(key))


def _uuid(row: Mapping[str, object], key: str) -> UUID:
    value = row.get(key)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid") from error


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid")
    return value


def _nullable_text(row: Mapping[str, object], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid")
    return value


def _integer(row: Mapping[str, object], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid") from error
    if result < 0:
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid")
    return result


def _datetime(row: Mapping[str, object], key: str) -> datetime:
    value = row.get(key)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PostgresSamplingSuiteError(f"Sampling Suite {key} is invalid")
    return value.astimezone(UTC)


def _input_id(project_id: UUID, option_key: str) -> UUID:
    return uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{project_id}:{option_key.strip()}")


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _canonical_utf8_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _hash_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise PostgresSamplingSuiteError("Idempotency-Key is required")
    return _hash({"idempotency_key": key})


__all__ = [
    "PersistentSamplingSuiteInput",
    "PostgresSamplingSuiteError",
    "PostgresSamplingSuiteRepository",
    "SAMPLING_SUITE_INPUT_NAMESPACE",
]
