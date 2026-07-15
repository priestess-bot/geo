from __future__ import annotations

import hashlib
import html
from typing import Any

import bleach
import markdown
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright
from pydantic import BaseModel, Field

from geo_core.runtime import validate_runtime_schema_compatibility


app = FastAPI(title="GEO Report PDF Renderer", version="1.0.0")


@app.on_event("startup")
def validate_schema_compatibility_on_startup() -> None:
    validate_runtime_schema_compatibility()


class PdfRenderRequest(BaseModel):
    markdown: str = Field(min_length=1, max_length=2_000_000)
    title: str = Field(default="GEO Evidence Report", min_length=1, max_length=200)


ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


def _report_html(markdown_text: str, title: str) -> str:
    rendered = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    safe_body = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={"a": ["href", "title"]},
        protocols={"http", "https"},
        strip=True,
    )
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{safe_title}</title>
  <style>
    @page {{ size: A4; margin: 17mm 15mm 19mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      color: #17202a;
      font-family: "Noto Sans CJK SC", "Noto Sans CJK", "Noto Sans", sans-serif;
      font-size: 10.5pt;
      line-height: 1.55;
      margin: 0;
    }}
    h1 {{ font-size: 23pt; margin: 0 0 14mm; color: #102a43; }}
    h2 {{ font-size: 15pt; margin: 9mm 0 3mm; color: #0b6e69; break-after: avoid; }}
    h3, h4 {{ font-size: 12pt; margin: 6mm 0 2mm; break-after: avoid; }}
    p, li {{ orphans: 3; widows: 3; }}
    table {{ border-collapse: collapse; width: 100%; margin: 4mm 0; font-size: 9pt; }}
    thead {{ display: table-header-group; }}
    tr {{ break-inside: avoid; }}
    th, td {{ border: 1px solid #cbd5df; padding: 2.2mm; text-align: left; vertical-align: top; }}
    th {{ background: #edf7f6; color: #143c3a; }}
    code {{ background: #f2f4f7; padding: 0.3mm 1mm; overflow-wrap: anywhere; }}
    pre {{ background: #f2f4f7; padding: 3mm; white-space: pre-wrap; overflow-wrap: anywhere; }}
    a {{ color: #075985; overflow-wrap: anywhere; }}
    blockquote {{ border-left: 3px solid #0b6e69; margin-left: 0; padding-left: 4mm; color: #475569; }}
  </style>
</head>
<body>{safe_body}</body>
</html>"""


def render_pdf(markdown_text: str, title: str) -> bytes:
    document = _report_html(markdown_text, title)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        try:
            page = browser.new_page(locale="zh-CN")

            def block_network(route: Any) -> None:
                if route.request.url.startswith(("http://", "https://")):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", block_network)
            page.set_content(document, wait_until="load")
            return page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<span></span>",
                footer_template=(
                    '<div style="width:100%;font-size:8px;color:#64748b;text-align:center">'
                    '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
                ),
                margin={"top": "17mm", "right": "15mm", "bottom": "19mm", "left": "15mm"},
            )
        finally:
            browser.close()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "renderer": "playwright-chromium", "network_access": "blocked"}


@app.post("/v1/render")
def render(payload: PdfRenderRequest) -> Response:
    try:
        content = render_pdf(payload.markdown, payload.title)
    except PlaywrightError as exc:
        raise HTTPException(status_code=503, detail=f"Chromium PDF rendering failed: {exc}") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "X-GEO-PDF-Renderer": "playwright-chromium-v1",
            "X-GEO-PDF-SHA256": hashlib.sha256(content).hexdigest(),
        },
    )
