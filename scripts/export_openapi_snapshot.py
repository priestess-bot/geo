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
DEFAULT_SNAPSHOT_PATH = ROOT / "contracts/openapi/geno-api.openapi.json"
DEFAULT_MANIFEST_PATH = ROOT / "contracts/openapi/manifest.json"
MANIFEST_VERSION = 1
HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
REQUIRED_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("/health", "get"),
    ("/v1/auth/invitations/preflight", "post"),
    ("/v1/auth/invitations/redeem", "post"),
    ("/v1/auth/me", "get"),
    ("/v1/projects/runtime", "get"),
)
ISOLATED_ENVIRONMENT = {
    "GENO_DEPLOYMENT_ENVIRONMENT": "development",
    "GENO_DEV_TOOLS_ENABLED": "0",
    "GENO_RUNTIME_AUTH_MODE": "header",
    "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "0",
}


class OpenAPISnapshotError(RuntimeError):
    """Raised when the checked-in OpenAPI contract is invalid or stale."""


@contextmanager
def isolated_openapi_environment() -> Iterator[None]:
    original = dict(os.environ)
    os.environ.clear()
    os.environ.update(ISOLATED_ENVIRONMENT)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _ensure_import_paths() -> None:
    for path in (ROOT, ROOT / "apps/api", ROOT / "packages/geno_core"):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def generate_openapi_document() -> dict[str, Any]:
    _ensure_import_paths()
    with isolated_openapi_environment():
        module = importlib.import_module("geno_api.main")
        app = module.app
        app.openapi_schema = None
        document = app.openapi()
    if not isinstance(document, dict):
        raise OpenAPISnapshotError("FastAPI returned a non-object OpenAPI document")
    validate_openapi_document(document)
    return document


def validate_openapi_document(document: Mapping[str, Any]) -> None:
    openapi_version = document.get("openapi")
    info = document.get("info")
    paths = document.get("paths")
    if not isinstance(openapi_version, str) or not openapi_version.strip():
        raise OpenAPISnapshotError("OpenAPI document has no version")
    if not isinstance(info, dict) or not isinstance(info.get("title"), str):
        raise OpenAPISnapshotError("OpenAPI document has no API title")
    if not isinstance(info.get("version"), str):
        raise OpenAPISnapshotError("OpenAPI document has no API version")
    if not isinstance(paths, dict):
        raise OpenAPISnapshotError("OpenAPI document has no paths object")

    for path, method in REQUIRED_OPERATIONS:
        path_item = paths.get(path)
        if not isinstance(path_item, dict) or not isinstance(path_item.get(method), dict):
            raise OpenAPISnapshotError(
                f"required OpenAPI operation is missing: {method.upper()} {path}"
            )

    operation_ids: dict[str, str] = {}
    for path in sorted(paths):
        path_item = paths[path]
        if not isinstance(path_item, dict):
            raise OpenAPISnapshotError(f"OpenAPI path item must be an object: {path}")
        for method in sorted(HTTP_METHODS & set(path_item)):
            operation = path_item[method]
            if not isinstance(operation, dict):
                raise OpenAPISnapshotError(
                    f"OpenAPI operation must be an object: {method} {path}"
                )
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise OpenAPISnapshotError(
                    f"OpenAPI operationId is missing: {method} {path}"
                )
            operation_ref = f"{method.upper()} {path}"
            previous = operation_ids.setdefault(operation_id, operation_ref)
            if previous != operation_ref:
                raise OpenAPISnapshotError(
                    f"duplicate OpenAPI operationId {operation_id!r}: "
                    f"{previous} and {operation_ref}"
                )


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def snapshot_bytes(document: Mapping[str, Any]) -> bytes:
    validate_openapi_document(document)
    return canonical_json_bytes(document)


def _operation_count(document: Mapping[str, Any]) -> int:
    paths = document["paths"]
    return sum(
        1
        for path_item in paths.values()
        for method in path_item
        if method in HTTP_METHODS
    )


def build_manifest(
    document: Mapping[str, Any],
    content: bytes,
    *,
    snapshot_file: str,
) -> dict[str, Any]:
    info = document["info"]
    return {
        "manifest_version": MANIFEST_VERSION,
        "artifact": {
            "file": snapshot_file,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        },
        "openapi": {
            "api_title": info["title"],
            "api_version": info["version"],
            "document_version": document["openapi"],
            "operation_count": _operation_count(document),
            "path_count": len(document["paths"]),
        },
    }


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(content)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def export_snapshot(*, snapshot_path: Path, manifest_path: Path) -> str:
    document = generate_openapi_document()
    content = snapshot_bytes(document)
    manifest = build_manifest(document, content, snapshot_file=snapshot_path.name)
    _atomic_write(snapshot_path, content)
    _atomic_write(manifest_path, canonical_json_bytes(manifest))
    return manifest["artifact"]["sha256"]


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
        payload = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenAPISnapshotError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenAPISnapshotError(f"{label} must contain a JSON object: {path}")
    return payload, content


def verify_snapshot(*, snapshot_path: Path, manifest_path: Path) -> str:
    checked_document, checked_content = _read_json_object(
        snapshot_path,
        label="OpenAPI snapshot",
    )
    validate_openapi_document(checked_document)
    if checked_content != snapshot_bytes(checked_document):
        raise OpenAPISnapshotError("checked-in OpenAPI snapshot is not canonically serialized")

    checked_manifest, manifest_content = _read_json_object(
        manifest_path,
        label="OpenAPI manifest",
    )
    expected_manifest = build_manifest(
        checked_document,
        checked_content,
        snapshot_file=snapshot_path.name,
    )
    if manifest_content != canonical_json_bytes(checked_manifest):
        raise OpenAPISnapshotError("OpenAPI manifest is not canonically serialized")
    if checked_manifest != expected_manifest:
        raise OpenAPISnapshotError("OpenAPI manifest does not match the checked-in snapshot")

    generated_content = snapshot_bytes(generate_openapi_document())
    if generated_content != checked_content:
        raise OpenAPISnapshotError(
            "checked-in OpenAPI snapshot is stale; run `make openapi-snapshot`"
        )
    return expected_manifest["artifact"]["sha256"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export or verify the canonical FastAPI OpenAPI snapshot"
    )
    parser.add_argument("command", choices=("export", "verify"))
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "export":
            digest = export_snapshot(snapshot_path=args.snapshot, manifest_path=args.manifest)
            print(f"OpenAPI snapshot exported: sha256={digest}")
        else:
            digest = verify_snapshot(snapshot_path=args.snapshot, manifest_path=args.manifest)
            print(f"OpenAPI snapshot verified: sha256={digest}")
    except OpenAPISnapshotError as exc:
        print(f"openapi snapshot error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
