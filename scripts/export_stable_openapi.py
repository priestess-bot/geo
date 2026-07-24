"""Export deterministic OpenAPI contracts from the two stable GEO API entrypoints."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "contracts" / "openapi" / "stable"
SURFACE_MODULES = {
    "internal": "geo_api.internal_app",
    "customer": "geo_api.customer_app",
}
SNAPSHOT_NAMES = {
    "internal": "internal.openapi.json",
    "customer": "customer.openapi.json",
}
MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
MUTATING_METHODS = frozenset({"post", "put", "patch", "delete"})
SHARED_REQUIRED_OPERATIONS = (
    ("get", "/health"),
    ("get", "/ready"),
    ("get", "/v1/auth/me"),
    ("post", "/v1/auth/logout"),
    ("get", "/v1/projects"),
)
INTERNAL_REQUIRED_OPERATIONS = (
    ("get", "/v1/jobs"),
    ("get", "/v1/jobs/{job_id}"),
    ("post", "/v1/projects"),
    ("get", "/v1/projects/{project_id}"),
    ("patch", "/v1/projects/{project_id}"),
    ("post", "/v1/projects/{project_id}/entities"),
    ("get", "/v1/projects/{project_id}/entities"),
    ("post", "/v1/projects/{project_id}/market-profiles"),
    ("get", "/v1/projects/{project_id}/market-profiles"),
    ("post", "/v1/projects/{project_id}/evidence-items"),
    ("get", "/v1/projects/{project_id}/evidence-items"),
    ("post", "/v1/projects/{project_id}/monitoring-protocols"),
    ("get", "/v1/projects/{project_id}/monitoring-protocols"),
    ("post", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/query-suggestions"),
    ("get", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/query-suggestions"),
    (
        "post",
        "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/query-suggestions/{suggestion_id}/approve",
    ),
    ("post", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/approve"),
    ("post", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/freeze"),
    ("post", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/observations"),
    ("get", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/observations"),
    ("post", "/v1/projects/{project_id}/monitoring-protocols/{protocol_id}/metrics"),
    ("get", "/v1/projects/{project_id}/monitoring-metrics"),
    ("post", "/v1/projects/{project_id}/monitoring-reports"),
    ("get", "/v1/projects/{project_id}/monitoring-reports"),
    ("post", "/v1/projects/{project_id}/monitoring-reports/{report_id}/approve"),
    ("get", "/v1/engineering/status"),
    ("get", "/v1/engineering/work-items"),
    ("get", "/v1/engineering/events"),
    ("post", "/v1/engineering/reconciliations"),
    ("post", "/v1/engineering/health-probes"),
    ("post", "/v1/integrations/github/events"),
    ("post", "/v1/projects/{project_id}/recommendations"),
    ("get", "/v1/projects/{project_id}/recommendations"),
    ("post", "/v1/projects/{project_id}/recommendations/generation-jobs"),
    ("get", "/v1/projects/{project_id}/recommendations/generation-jobs/{job_id}"),
    (
        "post",
        "/v1/projects/{project_id}/recommendations/generation-jobs/{job_id}/cancel",
    ),
    ("get", "/v1/projects/{project_id}/recommendations/{recommendation_id}"),
    ("post", "/v1/projects/{project_id}/recommendations/{recommendation_id}/submit"),
    ("post", "/v1/projects/{project_id}/recommendations/{recommendation_id}/review"),
    ("post", "/v1/projects/{project_id}/recommendations/{recommendation_id}/approve"),
    ("post", "/v1/projects/{project_id}/recommendations/{recommendation_id}/reject"),
    ("post", "/v1/projects/{project_id}/recommendations/{recommendation_id}/expire"),
    (
        "post",
        "/v1/projects/{project_id}/recommendations/{recommendation_id}/reconcile-stale",
    ),
    (
        "post",
        "/v1/projects/{project_id}/recommendations/{recommendation_id}/drafts/{draft_id}/prepare-action",
    ),
    ("get", "/v1/projects/{project_id}/synthetic-lab/authorizations"),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/authorizations/{authorization_id}/decision",
    ),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/authorizations/{authorization_id}/revoke",
    ),
    ("get", "/v1/projects/{project_id}/synthetic-lab/style-sources"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/style-sources"),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/sample-import-previews",
    ),
    ("get", "/v1/projects/{project_id}/synthetic-lab/style-profiles"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/style-profiles"),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/style-profiles/{profile_version_id}/freeze",
    ),
    ("get", "/v1/projects/{project_id}/synthetic-lab/review-suites"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/review-suites"),
    (
        "get",
        "/v1/projects/{project_id}/synthetic-lab/review-suites/{suite_version_id}/cases",
    ),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/review-suites/{suite_version_id}/cases",
    ),
    (
        "post",
        "/v1/projects/{project_id}/synthetic-lab/review-suites/{suite_version_id}/freeze",
    ),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/generation"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/revision"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/corpus"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/offline-experiment"),
    ("get", "/v1/projects/{project_id}/synthetic-lab/jobs/{job_id}"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/{job_id}/cancel"),
    ("post", "/v1/projects/{project_id}/synthetic-lab/jobs/{job_id}/finalize"),
    ("get", "/v1/projects/{project_id}/sampling/suite-input-options"),
    ("get", "/v1/projects/{project_id}/sampling/admission-options"),
    ("get", "/v1/projects/{project_id}/sampling/suites"),
    ("post", "/v1/projects/{project_id}/sampling/suites"),
    ("post", "/v1/projects/{project_id}/sampling/admission-policies"),
    ("get", "/v1/projects/{project_id}/sampling/admission-policies"),
    ("get", "/v1/projects/{project_id}/sampling/admission-policies/{policy_id}"),
    (
        "post",
        "/v1/projects/{project_id}/sampling/admission-policies/{policy_id}/submit",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/admission-policies/{policy_id}/approve",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/admission-policies/{policy_id}/assess-no-basis",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/admission-policies/{policy_id}/revoke",
    ),
    ("get", "/v1/projects/{project_id}/sampling/suites/{suite_id}"),
    ("post", "/v1/projects/{project_id}/sampling/suites/{suite_id}/runs"),
    ("get", "/v1/projects/{project_id}/sampling/runs"),
    ("get", "/v1/projects/{project_id}/sampling/runs/{run_id}"),
    ("post", "/v1/projects/{project_id}/sampling/runs/{run_id}/cancel"),
    ("post", "/v1/projects/{project_id}/sampling/runs/{run_id}/enqueue-ready"),
    (
        "post",
        "/v1/projects/{project_id}/sampling/runs/{run_id}/tasks/{task_id}/manual-evidence",
    ),
    ("get", "/v1/projects/{project_id}/sampling/manual-evidence-imports"),
    (
        "get",
        "/v1/projects/{project_id}/sampling/manual-evidence-imports/{import_id}",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/manual-evidence-imports/{import_id}/approve",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/manual-evidence-imports/{import_id}/reject",
    ),
    (
        "post",
        "/v1/projects/{project_id}/sampling/runs/{run_id}/tasks/{task_id}/attempts",
    ),
    ("post", "/v1/projects/{project_id}/sampling/attempts/{attempt_id}/cancel"),
    (
        "post",
        "/v1/projects/{project_id}/analysis/semantic-metrics/compute",
    ),
    ("get", "/v1/projects/{project_id}/analysis/semantic-metrics"),
    ("get", "/v1/projects/{project_id}/analysis/semantic-metrics/{snapshot_hash}"),
    ("post", "/v1/projects/{project_id}/analysis/comparisons/analyze"),
    ("get", "/v1/projects/{project_id}/analysis/comparisons"),
    ("get", "/v1/projects/{project_id}/analysis/comparisons/{family_hash}"),
    ("post", "/v1/projects/{project_id}/analysis/drift/compute"),
    ("get", "/v1/projects/{project_id}/analysis/drift"),
    ("get", "/v1/projects/{project_id}/analysis/drift/{report_hash}"),
    ("get", "/v1/projects/{project_id}/alerts"),
    ("get", "/v1/projects/{project_id}/alerts/{alert_id}"),
    ("get", "/v1/projects/{project_id}/alerts/{alert_id}/notifications"),
    ("post", "/v1/projects/{project_id}/alerts/{alert_id}/acknowledge"),
    ("post", "/v1/projects/{project_id}/alerts/{alert_id}/suppress"),
    ("post", "/v1/projects/{project_id}/alerts/{alert_id}/unsuppress"),
    ("post", "/v1/projects/{project_id}/alerts/{alert_id}/resolve"),
    ("get", "/v1/projects/{project_id}/prompt-bootstrap"),
    ("post", "/v1/projects/{project_id}/prompt-bootstrap/evaluate"),
    ("post", "/v1/projects/{project_id}/prompt-bootstrap/drafts"),
)
CUSTOMER_REQUIRED_OPERATIONS = (
    ("get", "/v1/projects/{project_id}/geo/summary"),
    ("get", "/v1/projects/{project_id}/geo/verified-urls"),
    ("get", "/v1/projects/{project_id}/geo/metrics"),
    ("get", "/v1/projects/{project_id}/geo/measurement-windows"),
    ("get", "/v1/projects/{project_id}/geo/reports"),
)
CUSTOMER_FORBIDDEN_PREFIXES = (
    "/v1/engineering",
    "/v1/dev-tools",
    "/v1/integrations/github",
    "/v1/projects/{project_id}/recommendations",
    "/v1/projects/{project_id}/synthetic-lab",
    "/v1/projects/{project_id}/sampling",
    "/v1/projects/{project_id}/analysis",
    "/v1/projects/{project_id}/alerts",
    "/v1/projects/{project_id}/prompt-bootstrap",
)
CUSTOMER_ALLOWED_WRITES = frozenset(
    {
        ("post", "/v1/auth/logout"),
        ("post", "/v1/auth/invitations/preflight"),
        ("post", "/v1/auth/invitations/redeem"),
    }
)
ISOLATED_ENVIRONMENT = {
    "GEO_DEPLOYMENT_ENVIRONMENT": "contract",
    "GEO_DEV_TOOLS_ENABLED": "0",
}


class StableOpenAPIError(RuntimeError):
    """A stable API contract is invalid, stale or non-deterministic."""


@contextmanager
def isolated_environment() -> Iterator[None]:
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(ISOLATED_ENVIRONMENT)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _ensure_import_paths() -> None:
    for path in (ROOT, ROOT / "apps" / "api", ROOT / "packages" / "geo_core"):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def generate_documents() -> dict[str, dict[str, Any]]:
    """Read OpenAPI from stable entrypoint modules without loading the legacy app."""

    _ensure_import_paths()
    documents: dict[str, dict[str, Any]] = {}
    with isolated_environment():
        for surface, module_name in SURFACE_MODULES.items():
            module = importlib.import_module(module_name)
            module = importlib.reload(module)
            app = module.app
            app.openapi_schema = None
            document = app.openapi()
            if not isinstance(document, dict):
                raise StableOpenAPIError(f"{surface} FastAPI OpenAPI document is not an object")
            validate_document(surface, document)
            documents[surface] = document
    return documents


def validate_document(surface: str, document: Mapping[str, Any]) -> None:
    info = document.get("info")
    paths = document.get("paths")
    if not isinstance(document.get("openapi"), str):
        raise StableOpenAPIError(f"{surface} OpenAPI document has no specification version")
    if not isinstance(info, dict) or not isinstance(info.get("title"), str):
        raise StableOpenAPIError(f"{surface} OpenAPI document has no title")
    if not isinstance(paths, dict):
        raise StableOpenAPIError(f"{surface} OpenAPI paths must be an object")

    required: tuple[tuple[str, str], ...] = SHARED_REQUIRED_OPERATIONS
    if surface == "internal":
        required += INTERNAL_REQUIRED_OPERATIONS
    if surface == "customer":
        required += CUSTOMER_REQUIRED_OPERATIONS
    for method, path in required:
        path_item = paths.get(path)
        if not isinstance(path_item, dict) or not isinstance(path_item.get(method), dict):
            raise StableOpenAPIError(
                f"{surface} required operation is missing: {method.upper()} {path}"
            )

    operation_ids: dict[str, str] = {}
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            raise StableOpenAPIError(f"{surface} path item is not an object: {path}")
        for method in sorted(HTTP_METHODS & set(path_item)):
            operation = path_item[method]
            operation_id = operation.get("operationId") if isinstance(operation, dict) else None
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise StableOpenAPIError(
                    f"{surface} operationId is missing: {method.upper()} {path}"
                )
            current = f"{method.upper()} {path}"
            previous = operation_ids.setdefault(operation_id, current)
            if previous != current:
                raise StableOpenAPIError(
                    f"{surface} duplicate operationId {operation_id!r}: {previous} and {current}"
                )

    if surface == "customer":
        _validate_customer_isolation(paths)


def _validate_customer_isolation(paths: Mapping[str, Any]) -> None:
    for path, path_item in paths.items():
        if any(path.startswith(prefix) for prefix in CUSTOMER_FORBIDDEN_PREFIXES):
            raise StableOpenAPIError(f"customer contract exposes internal path: {path}")
        if not isinstance(path_item, dict):
            continue
        for method in MUTATING_METHODS & set(path_item):
            if (method, path) not in CUSTOMER_ALLOWED_WRITES:
                raise StableOpenAPIError(
                    f"customer contract exposes a non-customer write: {method.upper()} {path}"
                )


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _operation_count(document: Mapping[str, Any]) -> int:
    return sum(
        1
        for path_item in document["paths"].values()
        for method in path_item
        if method in HTTP_METHODS
    )


def build_manifest(
    documents: Mapping[str, Mapping[str, Any]], contents: Mapping[str, bytes]
) -> dict[str, Any]:
    surfaces: dict[str, object] = {}
    for surface in sorted(SURFACE_MODULES):
        document = documents[surface]
        content = contents[surface]
        surfaces[surface] = {
            "file": SNAPSHOT_NAMES[surface],
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "api_title": document["info"]["title"],
            "api_version": document["info"]["version"],
            "document_version": document["openapi"],
            "path_count": len(document["paths"]),
            "operation_count": _operation_count(document),
        }
    return {"manifest_version": MANIFEST_VERSION, "surfaces": surfaces}


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_contracts(*, output_dir: Path) -> dict[str, Any]:
    documents = generate_documents()
    contents = {surface: canonical_json_bytes(document) for surface, document in documents.items()}
    manifest = build_manifest(documents, contents)
    for surface, content in contents.items():
        _atomic_write(output_dir / SNAPSHOT_NAMES[surface], content)
    _atomic_write(output_dir / MANIFEST_NAME, canonical_json_bytes(manifest))
    return manifest


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise StableOpenAPIError(f"cannot read stable contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StableOpenAPIError(f"stable contract is not a JSON object: {path}")
    if content != canonical_json_bytes(value):
        raise StableOpenAPIError(f"stable contract is not canonically serialized: {path}")
    return value, content


def verify_contracts(*, output_dir: Path) -> dict[str, Any]:
    checked_documents: dict[str, dict[str, Any]] = {}
    checked_contents: dict[str, bytes] = {}
    for surface in SURFACE_MODULES:
        document, content = _read_object(output_dir / SNAPSHOT_NAMES[surface])
        validate_document(surface, document)
        checked_documents[surface] = document
        checked_contents[surface] = content
    checked_manifest, _ = _read_object(output_dir / MANIFEST_NAME)
    expected_manifest = build_manifest(checked_documents, checked_contents)
    if checked_manifest != expected_manifest:
        raise StableOpenAPIError("stable OpenAPI manifest does not match its snapshots")

    generated = generate_documents()
    for surface, document in generated.items():
        if canonical_json_bytes(document) != checked_contents[surface]:
            raise StableOpenAPIError(
                f"{surface} stable snapshot is stale; run `make openapi-snapshots`"
            )
    return expected_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export or verify both stable GEO OpenAPI contracts"
    )
    parser.add_argument("command", choices=("export", "verify"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            manifest = export_contracts(output_dir=args.output_dir)
            print(f"Stable OpenAPI contracts exported: {len(manifest['surfaces'])} surfaces")
        else:
            manifest = verify_contracts(output_dir=args.output_dir)
            print(f"Stable OpenAPI contracts verified: {len(manifest['surfaces'])} surfaces")
    except StableOpenAPIError as exc:
        print(f"stable OpenAPI contract error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
