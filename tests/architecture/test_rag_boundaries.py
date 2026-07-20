from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAG_ROOT = ROOT / "packages/geo_core/geo_core/rag"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    values.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return values


def test_stable_rag_contracts_native_and_selection_do_not_import_frameworks_or_benchmark() -> None:
    forbidden = ("llama_index", "graphrag", "benchmarks")
    for name in ("contracts.py", "native.py", "selection.py"):
        imports = _imports(RAG_ROOT / name)
        assert not any(
            item == value or item.startswith(f"{value}.") for item in imports for value in forbidden
        ), name


def test_llamaindex_is_confined_to_optional_adapter_and_never_reads_gold() -> None:
    adapter = (RAG_ROOT / "llamaindex.py").read_text(encoding="utf-8")
    other_product_files = [path for path in RAG_ROOT.glob("*.py") if path.name != "llamaindex.py"]
    assert "llama_index" in adapter
    assert "benchmarks" not in adapter
    assert "gold" not in adapter.casefold()
    assert all(
        "llama_index" not in path.read_text(encoding="utf-8") for path in other_product_files
    )


def test_llamaindex_dependency_is_exact_and_optional() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in pyproject
    assert "llama-index-core==0.14.23" in pyproject
