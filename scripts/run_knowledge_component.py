from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit


def _compact(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _blocks(text: str) -> list[dict[str, Any]]:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    return [
        {
            "page_number": 1,
            "block_index": index,
            "block_type": "paragraph",
            "text": paragraph,
            "bbox": None,
            "section_path": [],
            "html": None,
            "markdown": paragraph,
            "reading_order": index,
            "confidence": 1.0,
            "metadata": {},
        }
        for index, paragraph in enumerate(paragraphs[:500])
    ]


def _markdown_tables(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    tables: list[dict[str, Any]] = []
    current: list[str] = []
    for line in [*lines, ""]:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(line.strip())
            continue
        if len(current) >= 2 and any("---" in item for item in current[1:2]):
            rows = [[cell.strip() for cell in row.strip("|").split("|")] for row in current]
            tables.append(
                {
                    "page_number": 1,
                    "table_index": len(tables),
                    "caption": None,
                    "table_json": {"rows": rows},
                    "markdown": "\n".join(current),
                    "confidence": 1.0,
                    "quality_flags": [],
                }
            )
        current = []
    return tables


def _result(engine: str, text: str, *, engine_version: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    clean = text.strip()
    blocks = _blocks(clean)
    return {
        "adapter": {
            "engine": engine,
            "engine_version": engine_version,
            "adapter_version": "geo-parser-adapter-v1",
        },
        "pages": [{"page_number": 1, "text_preview": _compact(clean)[:500]}] if clean else [],
        "blocks": blocks,
        "tables": _markdown_tables(clean),
        "images": [],
        "ocr_spans": [],
        "metadata": {},
        "quality_signals": [] if blocks else [{"code": "parser_empty_text", "severity": "blocked"}],
        "artifacts": artifacts or [],
    }


def _parse_docling(path: Path) -> dict[str, Any]:
    import docling
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter
    from docling.document_converter import PdfFormatOption

    converter = DocumentConverter()
    if path.suffix.lower() == ".pdf":
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = True
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    markdown = converter.convert(str(path)).document.export_to_markdown()
    return _result(
        "docling",
        markdown,
        engine_version=str(getattr(docling, "__version__", "unknown")),
        artifacts=[{"artifact_type": "parser_markdown", "content": markdown}],
    )


def _parse_unstructured(path: Path) -> dict[str, Any]:
    import unstructured
    from unstructured.partition.auto import partition

    elements = partition(filename=str(path))
    text = "\n\n".join(str(element) for element in elements if str(element).strip())
    payload = _result("unstructured", text, engine_version=str(getattr(unstructured, "__version__", "unknown")))
    payload["metadata"]["element_count"] = len(elements)
    return payload


def _parse_markitdown(path: Path) -> dict[str, Any]:
    import importlib.metadata
    from markitdown import MarkItDown

    markdown = str(getattr(MarkItDown().convert(str(path)), "text_content", "") or "")
    return _result(
        "markitdown",
        markdown,
        engine_version=importlib.metadata.version("markitdown"),
        artifacts=[{"artifact_type": "parser_markdown", "content": markdown}],
    )


def _parse_tika(path: Path) -> dict[str, Any]:
    import importlib.metadata
    from tika import parser

    parsed = parser.from_file(str(path))
    payload = _result("tika", str(parsed.get("content") or ""), engine_version=importlib.metadata.version("tika"))
    payload["metadata"]["tika_metadata"] = parsed.get("metadata") or {}
    return payload


def _parse_mineru(path: Path) -> dict[str, Any]:
    executable = Path(sys.executable).with_name("magic-pdf")
    if not executable.exists():
        discovered = shutil.which("magic-pdf")
        if not discovered:
            raise RuntimeError("magic-pdf executable is not available")
        executable = Path(discovered)
    with tempfile.TemporaryDirectory(prefix="geo-mineru-") as tmp:
        output = Path(tmp)
        completed = subprocess.run(
            [str(executable), "-p", str(path), "-o", str(output), "-m", "auto"],
            text=True,
            capture_output=True,
            check=False,
            timeout=420,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"MinerU failed: {completed.stderr[-2000:]}")
        markdown_paths = sorted(output.rglob("*.md"))
        if not markdown_paths:
            raise RuntimeError("MinerU completed without a Markdown artifact")
        markdown = markdown_paths[0].read_text(encoding="utf-8", errors="replace")
        json_artifacts = []
        content_items: list[dict[str, Any]] = []
        for artifact_path in sorted(output.rglob("*.json"))[:10]:
            raw_json = artifact_path.read_text(encoding="utf-8", errors="replace")
            json_artifacts.append(
                {
                    "artifact_type": "parser_json",
                    "name": artifact_path.name,
                    "content": raw_json,
                }
            )
            if "content_list" in artifact_path.stem:
                try:
                    parsed_json = json.loads(raw_json)
                    if isinstance(parsed_json, list):
                        content_items = [dict(item) for item in parsed_json if isinstance(item, dict)]
                except json.JSONDecodeError:
                    pass
        payload = _result(
            "mineru",
            markdown,
            engine_version="magic-pdf-1.3.10",
            artifacts=[{"artifact_type": "parser_markdown", "content": markdown}, *json_artifacts],
        )
        ocr_spans: list[dict[str, Any]] = []
        mineru_tables: list[dict[str, Any]] = []
        page_numbers: set[int] = set()
        for item in content_items:
            page_number = int(item.get("page_idx") or item.get("page_number") or 0) + 1
            page_numbers.add(page_number)
            item_type = str(item.get("type") or item.get("content_type") or "").lower()
            text = str(item.get("text") or item.get("content") or item.get("table_body") or "").strip()
            if text and item_type in {"text", "title", "header", "footer", "interline_equation"}:
                ocr_spans.append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "confidence": item.get("score") or item.get("confidence"),
                        "bbox": item.get("bbox"),
                        "metadata": {"mineru_type": item_type},
                    }
                )
            if item_type == "table":
                mineru_tables.append(
                    {
                        "page_number": page_number,
                        "table_index": len(mineru_tables),
                        "caption": item.get("table_caption") or item.get("caption"),
                        "table_json": {"html": item.get("table_body") or item.get("html"), "raw": item},
                        "markdown": text,
                        "confidence": item.get("score") or item.get("confidence"),
                        "quality_flags": [],
                    }
                )
        if ocr_spans:
            payload["ocr_spans"] = ocr_spans
        if mineru_tables:
            payload["tables"] = mineru_tables
        if page_numbers:
            payload["pages"] = [
                {"page_number": page_number, "text_preview": "", "metadata": {"source": "mineru_content_list"}}
                for page_number in sorted(page_numbers)
            ]
        return payload


def parse_file(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.input)
    parsers = {
        "docling": _parse_docling,
        "mineru": _parse_mineru,
        "unstructured": _parse_unstructured,
        "markitdown": _parse_markitdown,
        "tika": _parse_tika,
    }
    parser = parsers.get(args.engine)
    if parser is None:
        raise ValueError(f"unsupported parser engine: {args.engine}")
    payload = parser(path)
    payload["source_asset_id"] = args.source_asset_id
    return payload


def embed_file(args: argparse.Namespace) -> dict[str, Any]:
    from sentence_transformers import SentenceTransformer

    texts = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        raise ValueError("embedding input must be a JSON string array")
    model = SentenceTransformer(args.model, device=args.device)
    vectors = model.encode(texts, normalize_embeddings=True)
    return {
        "model": args.model,
        "backend": "sentence-transformers",
        "dimension": len(vectors[0]) if len(vectors) else 0,
        "vectors": [[float(value) for value in vector] for vector in vectors],
    }


def _canonical_crawl_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _url_allowed(url: str, *, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    if exclude_patterns and any(fnmatch.fnmatch(url, pattern) for pattern in exclude_patterns):
        return False
    return not include_patterns or any(fnmatch.fnmatch(url, pattern) for pattern in include_patterns)


def _robots_allowed(url: str) -> bool:
    parsed = urlsplit(url)
    robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    parser = urllib.robotparser.RobotFileParser(robots_url)
    try:
        parser.read()
    except OSError:
        return True
    return parser.can_fetch("*", url)


async def _crawl(
    url: str,
    *,
    max_pages: int,
    depth_limit: int,
    crawl_mode: str,
    include_patterns: list[str],
    exclude_patterns: list[str],
    respect_robots: bool,
) -> dict[str, Any]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy, BrowserManager

    root = _canonical_crawl_url(url)
    root_host = urlsplit(root).netloc.lower()
    queue: list[tuple[str, int]] = [(root, 0)]
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    config = CrawlerRunConfig(screenshot=True, remove_overlay_elements=True, wait_until="domcontentloaded")
    browser_executable = os.getenv("GEO_CRAWL4AI_BROWSER_EXECUTABLE", "").strip()
    crawler_kwargs: dict[str, Any] = {}
    if browser_executable:
        if not Path(browser_executable).is_file():
            raise RuntimeError(f"configured Crawl4AI browser executable does not exist: {browser_executable}")

        class _ExecutableBrowserManager(BrowserManager):
            def _build_browser_args(self) -> dict[str, Any]:
                browser_args = super()._build_browser_args()
                browser_args["executable_path"] = browser_executable
                return browser_args

        browser_config = BrowserConfig(browser_type="chromium", headless=True)
        strategy = AsyncPlaywrightCrawlerStrategy(browser_config=browser_config)
        strategy.browser_manager = _ExecutableBrowserManager(browser_config=browser_config, logger=strategy.logger)
        crawler_kwargs["crawler_strategy"] = strategy
    async with AsyncWebCrawler(**crawler_kwargs) as crawler:
        while queue and len(pages) < max_pages:
            current_url, depth = queue.pop(0)
            current_url = _canonical_crawl_url(current_url)
            if current_url in seen or not _url_allowed(
                current_url, include_patterns=include_patterns, exclude_patterns=exclude_patterns
            ):
                continue
            seen.add(current_url)
            if respect_robots and not await asyncio.to_thread(_robots_allowed, current_url):
                failures.append({"url": current_url, "error": "robots_disallowed"})
                continue
            result = await crawler.arun(url=current_url, config=config)
            if not bool(getattr(result, "success", False)):
                failures.append(
                    {
                        "url": current_url,
                        "error": str(getattr(result, "error_message", "Crawl4AI failed") or "Crawl4AI failed"),
                    }
                )
                continue
            markdown = str(getattr(result, "markdown", "") or "")
            html = str(getattr(result, "html", "") or "")
            normalized_url = _canonical_crawl_url(str(getattr(result, "url", "") or current_url))
            pages.append(
                {
                    "normalized_url": normalized_url,
                    "title": str((getattr(result, "metadata", None) or {}).get("title") or normalized_url),
                    "markdown": markdown,
                    "html": html,
                    "screenshot_base64": str(getattr(result, "screenshot", "") or ""),
                    "status_code": int(getattr(result, "status_code", 200) or 200),
                    "depth": depth,
                }
            )
            if depth >= depth_limit:
                if crawl_mode != "sitemap" or current_url != root:
                    continue
            links = (getattr(result, "links", None) or {}).get("internal") or []
            if crawl_mode == "sitemap" and current_url == root:
                sitemap_text = f"{html}\n{markdown}"
                links = [
                    {"href": value}
                    for value in re.findall(r"<loc>\s*(https?://[^<]+)\s*</loc>", sitemap_text, flags=re.IGNORECASE)
                ]
            for link in links:
                href = str((link or {}).get("href") or "").strip()
                if not href:
                    continue
                child_url = _canonical_crawl_url(urljoin(normalized_url, href))
                if urlsplit(child_url).scheme not in {"http", "https"} or urlsplit(child_url).netloc.lower() != root_host:
                    continue
                edges.append({"source": normalized_url, "target": child_url})
                if child_url not in seen:
                    queue.append((child_url, depth + 1))
    if not pages:
        raise RuntimeError(f"Crawl4AI produced no usable pages: {failures[:3]}")
    first = pages[0]
    return {
        **first,
        "pages": pages,
        "link_graph": {"root": root, "edges": edges},
        "crawled_page_count": len(pages),
        "failed_page_count": len(failures),
        "failures": failures,
    }


def crawl_url(args: argparse.Namespace) -> dict[str, Any]:
    return asyncio.run(
        _crawl(
            args.url,
            max_pages=args.max_pages,
            depth_limit=args.depth_limit,
            crawl_mode=args.crawl_mode,
            include_patterns=list(args.include_pattern or []),
            exclude_patterns=list(args.exclude_pattern or []),
            respect_robots=bool(args.respect_robots),
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute an isolated GEO knowledge component.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_parser = subparsers.add_parser("parse")
    parse_parser.add_argument("--engine", required=True)
    parse_parser.add_argument("--input", required=True)
    parse_parser.add_argument("--source-asset-id", required=True)
    parse_parser.add_argument("--output", required=True)

    embed_parser = subparsers.add_parser("embed")
    embed_parser.add_argument("--input", required=True)
    embed_parser.add_argument("--output", required=True)
    embed_parser.add_argument("--model", required=True)
    embed_parser.add_argument("--device", default="cpu")

    crawl_parser = subparsers.add_parser("crawl")
    crawl_parser.add_argument("--url", required=True)
    crawl_parser.add_argument("--output", required=True)
    crawl_parser.add_argument("--max-pages", type=int, default=1)
    crawl_parser.add_argument("--depth-limit", type=int, default=0)
    crawl_parser.add_argument("--crawl-mode", choices=("single_url", "url_batch", "site_depth", "sitemap"), default="single_url")
    crawl_parser.add_argument("--include-pattern", action="append", default=[])
    crawl_parser.add_argument("--exclude-pattern", action="append", default=[])
    crawl_parser.add_argument("--respect-robots", action=argparse.BooleanOptionalAction, default=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "parse":
            payload = parse_file(args)
        elif args.command == "embed":
            payload = embed_file(args)
        else:
            payload = crawl_url(args)
        output = {"status": "pass", **payload}
    except Exception as exc:  # noqa: BLE001
        output = {"status": "fail", "error_type": type(exc).__name__, "error": str(exc)}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    if output["status"] != "pass":
        print(json.dumps(output, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
