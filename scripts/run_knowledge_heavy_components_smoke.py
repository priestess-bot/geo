from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_COMPONENT_PYTHONS = {
    "docling": "/opt/venvs/docling/bin/python",
    "mineru": "/opt/venvs/mineru/bin/python",
    "unstructured": "/opt/venvs/unstructured/bin/python",
    "markitdown": "/opt/venvs/markitdown/bin/python",
    "tika": "/opt/venvs/tika/bin/python",
    "crawl4ai": "/opt/venvs/crawl4ai/bin/python",
    "bge_m3": "/opt/venvs/bge/bin/python",
}


def _json_result(status: str, **payload: Any) -> str:
    return json.dumps({"status": status, **payload}, ensure_ascii=False)


def _write_minimal_pdf(path: Path, text: str) -> None:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(b"".join(chunks))


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def _start_local_site(root: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/sample.html"


def _make_samples(root: Path) -> dict[str, str]:
    sample_text = (
        "KoalaHome is an Australian homewares brand. "
        "It offers delivery, returns, warranty support, and customer reviews."
    )
    sample_html = """<!doctype html>
<html>
  <head><title>KoalaHome Knowledge Smoke</title></head>
  <body>
    <main>
      <h1>KoalaHome delivery and returns</h1>
      <p>KoalaHome provides Australian homewares with tracked delivery and 30 day returns.</p>
      <table>
        <thead><tr><th>Topic</th><th>Fact</th></tr></thead>
        <tbody>
          <tr><td>Warranty</td><td>Two year product warranty.</td></tr>
          <tr><td>Support</td><td>Melbourne based customer team.</td></tr>
        </tbody>
      </table>
    </main>
  </body>
</html>
"""
    sample_markdown = """# KoalaHome Knowledge Smoke

KoalaHome sells Australian homewares with tracked delivery, 30 day returns, and warranty support.

| Topic | Fact |
| --- | --- |
| Warranty | Two year product warranty |
| Support | Melbourne based customer team |
"""
    sample_csv = "topic,fact\nWarranty,Two year product warranty\nSupport,Melbourne based customer team\n"

    html = root / "sample.html"
    markdown = root / "sample.md"
    text = root / "sample.txt"
    csv = root / "sample.csv"
    pdf = root / "sample.pdf"
    html.write_text(sample_html, encoding="utf-8")
    markdown.write_text(sample_markdown, encoding="utf-8")
    text.write_text(sample_text, encoding="utf-8")
    csv.write_text(sample_csv, encoding="utf-8")
    _write_minimal_pdf(pdf, "KoalaHome delivery returns warranty support.")
    return {
        "html": str(html),
        "markdown": str(markdown),
        "text": str(text),
        "csv": str(csv),
        "pdf": str(pdf),
    }


def _extract_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _tail(value: str, limit: int = 4000) -> str:
    value = value.strip()
    return value[-limit:] if len(value) > limit else value


def _component_python(name: str) -> str:
    env_name = f"GEO_{name.upper()}_PYTHON"
    configured = os.getenv(env_name, "").strip()
    if configured:
        return configured
    container_path = Path(DEFAULT_COMPONENT_PYTHONS[name])
    if container_path.exists():
        return str(container_path)
    local_path = ROOT / ".venvs" / "knowledge-heavy" / ("bge" if name == "bge_m3" else name) / "bin" / "python"
    return str(local_path)


def _run_component(name: str, code: str, *, env: dict[str, str], timeout: int) -> dict[str, Any]:
    python_exe = _component_python(name)
    started = time.monotonic()
    if not Path(python_exe).exists():
        return {
            "status": "fail",
            "python": python_exe,
            "error": f"component python not found: {python_exe}",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    try:
        completed = subprocess.run(
            [python_exe, "-c", code],
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "fail",
            "python": python_exe,
            "error": f"component timed out after {timeout} seconds",
            "stdout": _tail(str(exc.stdout or "")),
            "stderr": _tail(str(exc.stderr or "")),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    elapsed = round(time.monotonic() - started, 3)
    payload = _extract_json(completed.stdout)
    if completed.returncode == 0 and payload and payload.get("status") == "pass":
        payload["python"] = python_exe
        payload["elapsed_seconds"] = elapsed
        return payload
    return {
        "status": "fail",
        "python": python_exe,
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "payload": payload,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }


DOCLING_CODE = r'''
import json
import os
from pathlib import Path
from scripts.run_knowledge_component import _parse_docling

paths = [Path(os.environ["GEO_SAMPLE_HTML"]), Path(os.environ["GEO_SAMPLE_PDF"])]
errors = []
outputs = []
for path in paths:
    try:
        result = _parse_docling(path)
        text = "\n".join(str(block.get("text") or "") for block in result.get("blocks") or [])
        if result.get("adapter", {}).get("adapter_version") == "geo-parser-adapter-v1" and "KoalaHome" in text:
            outputs.append({
                "input": path.name,
                "block_count": len(result.get("blocks") or []),
                "page_count": len(result.get("pages") or []),
                "table_count": len(result.get("tables") or []),
                "contains_brand": True,
            })
            continue
        errors.append(f"{path.name}: invalid GEO adapter output or missing KoalaHome")
    except Exception as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
if errors:
    print(json.dumps({"status": "fail", "outputs": outputs, "errors": errors}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({"status": "pass", "outputs": outputs}, ensure_ascii=False))
'''


UNSTRUCTURED_CODE = r'''
import json
import os
from unstructured.partition.auto import partition

elements = partition(filename=os.environ["GEO_SAMPLE_HTML"])
text = "\n".join(str(element) for element in elements)
if "KoalaHome" not in text:
    print(json.dumps({"status": "fail", "element_count": len(elements), "text": text[:300]}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({"status": "pass", "element_count": len(elements), "text_chars": len(text)}, ensure_ascii=False))
'''


MARKITDOWN_CODE = r'''
import json
import os
from markitdown import MarkItDown

result = MarkItDown().convert(os.environ["GEO_SAMPLE_HTML"])
markdown = str(getattr(result, "text_content", "") or "")
if "KoalaHome" not in markdown:
    print(json.dumps({"status": "fail", "markdown": markdown[:300]}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({"status": "pass", "markdown_chars": len(markdown)}, ensure_ascii=False))
'''


TIKA_CODE = r'''
import json
import os
from tika import parser

parsed = parser.from_file(os.environ["GEO_SAMPLE_TEXT"])
text = str(parsed.get("content") or "")
metadata = parsed.get("metadata") or {}
if "KoalaHome" not in text:
    print(json.dumps({"status": "fail", "text": text[:300], "metadata": metadata}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({"status": "pass", "text_chars": len(text), "metadata_keys": sorted(metadata.keys())[:10]}, ensure_ascii=False))
'''


CRAWL4AI_CODE = r'''
import asyncio
import json
import os
from scripts.run_knowledge_component import _crawl

async def main():
    result = await _crawl(
        os.environ["GEO_SAMPLE_URL"],
        max_pages=1,
        depth_limit=0,
        crawl_mode="single_url",
        include_patterns=[],
        exclude_patterns=[],
        respect_robots=False,
    )
    markdown = str(result.get("markdown") or "")
    html = str(result.get("html") or "")
    text = markdown or html
    if "KoalaHome" not in text:
        print(json.dumps({
            "status": "fail",
            "markdown": markdown[:300],
            "html": html[:300],
            "failures": result.get("failures") or [],
        }, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps({
        "status": "pass",
        "crawled_page_count": result.get("crawled_page_count"),
        "markdown_chars": len(markdown),
        "html_chars": len(html),
    }, ensure_ascii=False))

asyncio.run(main())
'''


BGE_M3_CODE = r'''
import json
import os
from sentence_transformers import SentenceTransformer

model_name = os.getenv("GEO_BGE_M3_MODEL", "BAAI/bge-m3")
model = SentenceTransformer(model_name, device="cpu")
vectors = model.encode(
    ["KoalaHome tracked delivery and warranty support"],
    normalize_embeddings=True,
)
dimension = len(vectors[0])
if dimension < 100:
    print(json.dumps({"status": "fail", "model": model_name, "dimension": dimension}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({"status": "pass", "model": model_name, "dimension": dimension}, ensure_ascii=False))
'''


MINERU_CODE = r'''
import json
import os
from pathlib import Path
from scripts.run_knowledge_component import _parse_mineru

pdf = Path(os.environ["GEO_SAMPLE_PDF"])
result = _parse_mineru(pdf)
text = "\n".join(str(block.get("text") or "") for block in result.get("blocks") or [])
markdown_artifacts = [item for item in result.get("artifacts") or [] if item.get("artifact_type") == "parser_markdown"]
if result.get("adapter", {}).get("adapter_version") != "geo-parser-adapter-v1" or "KoalaHome" not in text or not markdown_artifacts:
    print(json.dumps({"status": "fail", "result": result}, ensure_ascii=False))
    raise SystemExit(1)
print(json.dumps({
    "status": "pass",
    "block_count": len(result.get("blocks") or []),
    "page_count": len(result.get("pages") or []),
    "table_count": len(result.get("tables") or []),
    "ocr_span_count": len(result.get("ocr_spans") or []),
    "artifact_count": len(result.get("artifacts") or []),
    "contains_brand": True,
}, ensure_ascii=False))
'''


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="geo-heavy-components-") as tmp:
        root = Path(tmp)
        samples = _make_samples(root)
        server, url = _start_local_site(root)
        try:
            env = os.environ.copy()
            mineru_models = Path(os.getenv("GEO_MINERU_MODELS_DIR", str(ROOT / ".cache/models/mineru-pdf-extract-kit/models")))
            layoutreader_model = Path(os.getenv("GEO_LAYOUTREADER_MODEL_DIR", str(ROOT / ".cache/models/layoutreader")))
            mineru_config = root / "magic-pdf.json"
            mineru_config.write_text(
                json.dumps(
                    {
                        "bucket_info": {"[default]": [None, None, None]},
                        "models-dir": str(mineru_models),
                        "layoutreader-model-dir": str(layoutreader_model),
                        "device-mode": "cpu",
                        "layout-config": {"model": "doclayout_yolo"},
                        "formula-config": {
                            "mfd_model": "yolo_v8_mfd",
                            "mfr_model": "unimernet_small",
                            "enable": False,
                        },
                        "table-config": {"model": "rapid_table", "enable": False, "max_time": 400},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            env.update(
                {
                    "GEO_SAMPLE_HTML": samples["html"],
                    "GEO_SAMPLE_MARKDOWN": samples["markdown"],
                    "GEO_SAMPLE_TEXT": samples["text"],
                    "GEO_SAMPLE_CSV": samples["csv"],
                    "GEO_SAMPLE_PDF": samples["pdf"],
                    "GEO_SAMPLE_URL": url,
                    "GEO_MINERU_OUT": str(root / "mineru-output"),
                    "HF_HOME": os.getenv("HF_HOME", str(ROOT / ".cache/huggingface")),
                    "SENTENCE_TRANSFORMERS_HOME": os.getenv("SENTENCE_TRANSFORMERS_HOME", str(ROOT / ".cache/sentence-transformers")),
                    "TIKA_SERVER_JAR": os.getenv("TIKA_SERVER_JAR", str(ROOT / ".cache/tika/tika-server-standard-3.2.3.jar")),
                    "TIKA_LOG_PATH": str(root / "tika-log"),
                    "MINERU_TOOLS_CONFIG_JSON": os.getenv("MINERU_TOOLS_CONFIG_JSON", str(mineru_config)),
                    "GEO_BGE_M3_MODEL": os.getenv("GEO_BGE_M3_MODEL", str(ROOT / ".cache/models/bge-m3-pytorch")),
                }
            )
            Path(env["TIKA_LOG_PATH"]).mkdir(parents=True, exist_ok=True)
            chromium_candidates = [
                ROOT / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
                Path.home() / ".cache/ms-playwright/chromium-1228/chrome-linux64/chrome",
            ]
            chromium_candidates.extend(
                sorted((Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux*/chrome"))
            )
            local_chromium = next((path for path in chromium_candidates if path.is_file()), None)
            if local_chromium is not None and not env.get("GEO_CRAWL4AI_BROWSER_EXECUTABLE"):
                env["GEO_CRAWL4AI_BROWSER_EXECUTABLE"] = str(local_chromium)
            component_specs = {
                "docling": ("docling", DOCLING_CODE, args.parser_timeout),
                "mineru": ("mineru", MINERU_CODE, args.mineru_timeout),
                "unstructured": ("unstructured", UNSTRUCTURED_CODE, args.parser_timeout),
                "markitdown": ("markitdown", MARKITDOWN_CODE, args.parser_timeout),
                "tika": ("tika", TIKA_CODE, args.tika_timeout),
                "crawl4ai": ("crawl4ai", CRAWL4AI_CODE, args.crawl_timeout),
                "sentence_transformers_bge_m3": ("bge_m3", BGE_M3_CODE, args.bge_timeout),
            }
            requested = {value.strip() for value in args.components.split(",") if value.strip()}
            unknown = requested - set(component_specs)
            if unknown:
                raise ValueError(f"unknown knowledge components: {sorted(unknown)}")
            results = {}
            for result_name, (runtime_name, code, timeout) in component_specs.items():
                if requested and result_name not in requested:
                    continue
                results[result_name] = _run_component(runtime_name, code, env=env, timeout=timeout)
        finally:
            server.shutdown()
            server.server_close()
    failed = [name for name, payload in results.items() if payload.get("status") != "pass"]
    return {
        "status": "pass" if not failed else "fail",
        "failed_components": failed,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real smoke tests for heavy GEO knowledge components.")
    parser.add_argument("--artifact", default="/tmp/geo-knowledge-heavy-components-smoke.json")
    parser.add_argument("--parser-timeout", type=int, default=240)
    parser.add_argument("--mineru-timeout", type=int, default=420)
    parser.add_argument("--tika-timeout", type=int, default=240)
    parser.add_argument("--crawl-timeout", type=int, default=240)
    parser.add_argument("--bge-timeout", type=int, default=900)
    parser.add_argument(
        "--components",
        default="",
        help="Comma-separated component names; empty runs all production knowledge components.",
    )
    args = parser.parse_args(argv)
    payload = run_smoke(args)
    Path(args.artifact).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
