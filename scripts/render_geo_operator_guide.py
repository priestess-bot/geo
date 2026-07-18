#!/usr/bin/env python3
"""Render the standalone Markdown guide, merge a PaperJSX cover, and validate the PDF."""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import tempfile

import mistune
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs/operations/geo-ui-operator-guide.md"
DEFAULT_OUTPUT = ROOT / "docs/operations/ADVINSYS-GEO-全流程部署运维手册.pdf"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    value.add_argument("--receipt", type=Path)
    return value


def image_paths(markdown_text: str, base: Path) -> list[Path]:
    values = re.findall(r"!\[[^]]*\]\(([^)]+)\)", markdown_text)
    return [(base / value).resolve() for value in values if "://" not in value]


def document_html(markdown_text: str, base: Path) -> str:
    renderer = mistune.create_markdown(
        plugins=["table", "strikethrough", "task_lists", "url"]
    )
    body = renderer(markdown_text)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<base href="{html.escape(base.resolve().as_uri())}/">
<style>
@page {{ size:A4; margin:15mm 13mm 17mm; }}
* {{ box-sizing:border-box; }}
body {{ color:#17232b; font:10.2pt/1.58 "Noto Sans CJK SC","Microsoft YaHei",sans-serif; margin:0; }}
h1 {{ color:#0f4756; font-size:25pt; margin:0 0 12mm; }}
h2 {{ border-bottom:1px solid #b7c9ce; break-after:avoid; color:#0f4756; font-size:17pt; margin:10mm 0 4mm; padding-bottom:2mm; }}
h3 {{ break-after:avoid; color:#245d67; font-size:13pt; margin:7mm 0 2mm; }}
p,li {{ orphans:3; widows:3; }}
a {{ color:#126b7c; text-decoration:none; }}
table {{ border-collapse:collapse; font-size:8.8pt; margin:3mm 0 5mm; width:100%; }}
th,td {{ border:1px solid #c3d1d5; padding:2mm; text-align:left; vertical-align:top; }}
th {{ background:#eaf1f2; color:#24434b; }}
pre {{ background:#15252b; border-radius:3px; color:#edf6f7; font:7.8pt/1.5 monospace; overflow-wrap:anywhere; padding:3mm; white-space:pre-wrap; }}
code {{ font-family:monospace; overflow-wrap:anywhere; }}
blockquote {{ border-left:3px solid #3b7c85; margin-left:0; padding-left:4mm; }}
img {{ break-inside:avoid; display:block; height:auto; margin:4mm auto 6mm; max-height:215mm; max-width:100%; object-fit:contain; }}
input[type=checkbox] {{ appearance:none; border:1px solid #566; display:inline-block; height:9px; margin-right:4px; width:9px; }}
</style></head><body>{body}</body></html>"""


def main() -> int:
    args = parser().parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    markdown_text = source.read_text(encoding="utf-8")
    missing = [str(path) for path in image_paths(markdown_text, source.parent) if not path.is_file()]
    if missing:
        raise RuntimeError(f"manual references missing images: {missing}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="geo-operator-guide-") as temporary:
        temporary_path = Path(temporary)
        cover = temporary_path / "cover.pdf"
        body_pdf = temporary_path / "body.pdf"
        html_file = temporary_path / "guide.html"
        subprocess.run(
            [
                "node",
                str(ROOT / "scripts/pdf/render_geo_operator_cover.mjs"),
                str(cover),
                "1.0",
                date.today().isoformat(),
            ],
            cwd=ROOT,
            check=True,
        )
        html_file.write_text(document_html(markdown_text, source.parent), encoding="utf-8")
        console_errors: list[str] = []
        page_errors: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(html_file.as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(body_pdf),
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=(
                    '<div style="font:8px sans-serif;color:#607078;width:100%;text-align:center">'
                    "ADVINSYS GEO Operations Manual · "
                    '<span class="pageNumber"></span>/<span class="totalPages"></span></div>'
                ),
                margin={"top": "4mm", "bottom": "10mm", "left": "0", "right": "0"},
            )
            browser.close()
        if console_errors or page_errors:
            raise RuntimeError(
                f"browser rendering errors: console={console_errors}, page={page_errors}"
            )
        writer = PdfWriter()
        for path in (cover, body_pdf):
            for page in PdfReader(path).pages:
                writer.add_page(page)
        writer.add_metadata(
            {
                "/Title": "ADVINSYS GEO 项目部署与运维全流程操作手册",
                "/Author": "GEO Platform Engineering",
            }
        )
        with output.open("wb") as handle:
            writer.write(handle)

    reader = PdfReader(output)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    required = ("ADVINSYS", "Knowledge", "DeepSeek", "T+28", "Customer")
    missing_text = [value for value in required if value not in extracted]
    if output.stat().st_size == 0 or len(reader.pages) < 10 or missing_text:
        raise RuntimeError(
            f"PDF validation failed: pages={len(reader.pages)} missing_text={missing_text}"
        )
    result = {
        "generated_at": date.today().isoformat(),
        "input": str(source),
        "output": str(output),
        "pages": len(reader.pages),
        "bytes": output.stat().st_size,
        "image_references": len(image_paths(markdown_text, source.parent)),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "paperjsx_cover": True,
        "browser_body": True,
        "required_text_verified": list(required),
    }
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
