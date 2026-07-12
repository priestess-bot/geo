from __future__ import annotations

import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from geno_core.schema_compatibility import (
    DEFAULT_SCHEMA_CONNECT_TIMEOUT_SECONDS,
    _default_connector,
)


ROOT = Path(__file__).resolve().parents[1]

CLI_ENTRYPOINTS = {
    "workers/task_queue/run_recovery_dispatcher.py": "dispatch_background_task(",
    "workers/knowledge_worker/run_knowledge_pipeline.py": (
        "connect_knowledge_pipeline_repository()"
    ),
    "workers/report_export_worker/run_report_export_jobs.py": "build_repository_from_env()",
    "workers/collector_worker/run_collection_slice.py": (
        "lease_claim_from_internal_environment()"
    ),
    "workers/notification_worker/run_entity_alias_assignment_dispatch_apply.py": (
        "build_repository_from_env()"
    ),
    "workers/notification_worker/run_entity_alias_assignment_escalations.py": (
        "build_repository_from_env()"
    ),
    "workers/notification_worker/run_entity_alias_assignment_notifications.py": (
        "build_repository_from_env()"
    ),
    "workers/notification_worker/run_entity_alias_assignment_reassignments.py": (
        "build_repository_from_env()"
    ),
    "workers/notification_worker/run_notification_deliveries.py": "build_repository_from_env()",
    "workers/notification_worker/run_runtime_alert_escalations.py": "build_repository_from_env()",
    "workers/notification_worker/run_runtime_alert_notifications.py": "build_repository_from_env()",
}

HTTP_ENTRYPOINTS = (
    "workers/knowledge_worker/embedding_api.py",
    "workers/report_export_worker/pdf_renderer_api.py",
)


def _main_body(source: str) -> str:
    start = source.index("def main(")
    end = source.index('\nif __name__ == "__main__":', start)
    return source[start:end]


class WorkerSchemaCompatibilityContractsTest(unittest.TestCase):
    def test_cli_workers_validate_before_their_first_runtime_side_effect(self) -> None:
        for relative_path, first_side_effect in CLI_ENTRYPOINTS.items():
            with self.subTest(entrypoint=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                main_body = _main_body(source)
                validation_offset = main_body.index("validate_runtime_schema_compatibility()")
                side_effect_offset = main_body.index(first_side_effect)
                self.assertLess(validation_offset, side_effect_offset)

    def test_http_workers_validate_in_startup_hooks_not_at_import_time(self) -> None:
        for relative_path in HTTP_ENTRYPOINTS:
            with self.subTest(entrypoint=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                module = ast.parse(source)
                startup_functions = [
                    node
                    for node in module.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "on_event"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and decorator.args[0].value == "startup"
                        for decorator in node.decorator_list
                    )
                ]
                self.assertEqual(len(startup_functions), 1)
                calls = [
                    node
                    for node in ast.walk(startup_functions[0])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "validate_runtime_schema_compatibility"
                ]
                self.assertEqual(len(calls), 1)
                module_level_calls = [
                    node
                    for statement in module.body
                    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    for node in ast.walk(statement)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "validate_runtime_schema_compatibility"
                ]
                self.assertEqual(module_level_calls, [])

    def test_dramatiq_worker_validates_before_worker_boot(self) -> None:
        source = (ROOT / "workers/task_queue/tasks.py").read_text(encoding="utf-8")
        self.assertIn("class SchemaCompatibilityMiddleware(dramatiq.Middleware):", source)
        self.assertIn("def before_worker_boot(", source)
        self.assertIn("validate_runtime_schema_compatibility()", source)
        self.assertIn("broker.add_middleware(SchemaCompatibilityMiddleware())", source)

    def test_default_connector_uses_a_bounded_timeout_without_rewriting_the_dsn(self) -> None:
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        sentinel = object()

        def connect(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return sentinel

        fake_psycopg = SimpleNamespace(connect=connect)
        database_url = "postgresql://schema-user:SECRET@db.internal/geno_v2"
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            result = _default_connector(database_url)

        self.assertIs(result, sentinel)
        self.assertEqual(
            calls,
            [
                (
                    (database_url,),
                    {"connect_timeout": DEFAULT_SCHEMA_CONNECT_TIMEOUT_SECONDS},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
