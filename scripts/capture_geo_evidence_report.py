#!/usr/bin/env python3
"""Render command-backed GEO acceptance evidence as local screenshots."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import subprocess

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--acceptance-result", type=Path, required=True)
    value.add_argument("--browser-report", type=Path, required=True)
    value.add_argument("--backup-receipt", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def command(*arguments: str) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def service_rows() -> list[dict[str, object]]:
    raw = command(
        "docker",
        "compose",
        "-f",
        "infra/docker-compose.yml",
        "--profile",
        "workers",
        "ps",
        "--format",
        "json",
    )
    if not raw:
        return []
    return [json.loads(line) for line in raw.splitlines()]


def health(url: str) -> dict[str, object]:
    return json.loads(command("curl", "-fsS", url))


def card(title: str, body: str) -> str:
    return f'<section class="card"><h2>{html.escape(title)}</h2>{body}</section>'


def table(rows: list[tuple[str, object]]) -> str:
    values = "".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"
        for label, value in rows
    )
    return f"<table>{values}</table>"


def report_html(
    *, acceptance: dict[str, object], browser: list[dict[str, object]], backup: dict[str, object]
) -> str:
    services = service_rows()
    failures = [
        item
        for item in browser
        if item["console_errors"]
        or item["page_errors"]
        or item["failed_responses"]
        or item["horizontal_overflow"]
    ]
    service_body = "".join(
        f"<tr><td>{html.escape(str(item['Service']))}</td>"
        f"<td>{html.escape(str(item['State']))}</td>"
        f"<td>{html.escape(str(item.get('Health') or '-'))}</td></tr>"
        for item in services
    )
    model = command(
        "docker",
        "compose",
        "-f",
        "infra/docker-compose.yml",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-At",
        "-U",
        "geo_installer",
        "-d",
        "geo",
        "-c",
        "SELECT configured_model || ' / ' || COALESCE(provider_reported_model, '-') "
        f"FROM model_call_logs WHERE project_id = '{acceptance['project']['project_id']}' "
        "AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
    )
    sections = [
        card(
            "运行记录",
            table(
                [
                    ("Run ID", acceptance["run_id"]),
                    ("Commit", command("git", "rev-parse", "HEAD")),
                    ("Branch", command("git", "branch", "--show-current")),
                    ("Mode", acceptance["mode"]),
                    ("Project", acceptance["project"]["project_id"]),
                    ("Configured / reported model", model),
                    ("Browser views", len(browser)),
                    ("Browser failures", len(failures)),
                ]
            ),
        ),
        card(
            "服务健康",
            "<table><thead><tr><th>Service</th><th>State</th><th>Health</th></tr></thead>"
            f"<tbody>{service_body}</tbody></table>"
            + table(
                [
                    ("Internal API", health("http://localhost:8000/health")),
                    ("Customer API", health("http://localhost:8001/health")),
                ]
            ),
        ),
        card(
            "全流程断言",
            table([(key, value) for key, value in acceptance["assertions"].items()]),
        ),
        card(
            "备份与隔离恢复",
            table(
                [
                    ("Schema", backup["schema_version"]),
                    (
                        "PostgreSQL projects",
                        f"{backup['postgres']['source_project_count']} -> "
                        f"{backup['postgres']['restored_project_count']}",
                    ),
                    (
                        "PostgreSQL tables",
                        f"{backup['postgres']['source_table_count']} -> "
                        f"{backup['postgres']['restored_table_count']}",
                    ),
                    (
                        "MinIO objects",
                        f"{backup['object_store']['source_object_count']} -> "
                        f"{backup['object_store']['restored_object_count']}",
                    ),
                    (
                        "Per-object SHA-256",
                        backup["object_store"]["per_object_sha256_verified"],
                    ),
                    ("Restore copy removed", backup["restore_copy_removed"]),
                    ("Verified at", backup["verified_at"]),
                ]
            ),
        ),
    ]
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<style>
body {{ background:#f3f6f8; color:#1d2d38; font:14px system-ui; margin:0; padding:32px; }}
main {{ display:grid; gap:18px; margin:auto; max-width:1180px; }}
h1 {{ font-size:28px; margin:0; }} h2 {{ font-size:18px; margin:0 0 12px; }}
.meta {{ color:#607481; margin:4px 0 10px; }}
.card {{ background:#fff; border:1px solid #ccd8df; border-radius:6px; padding:20px; }}
table {{ border-collapse:collapse; width:100%; }} th,td {{ border-top:1px solid #dbe3e8; padding:9px; text-align:left; }}
th {{ color:#506773; width:30%; }} thead th {{ background:#edf2f5; }}
</style><main><header><h1>GEO 全流程验收证据</h1>
<p class="meta">由仓库命令、运行数据库和验收工件实时生成；不包含 Secret。</p></header>
{''.join(sections)}</main></html>"""


def main() -> int:
    args = parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    acceptance = json.loads(args.acceptance_result.read_text(encoding="utf-8"))
    browser = json.loads(args.browser_report.read_text(encoding="utf-8"))
    backup = json.loads(args.backup_receipt.read_text(encoding="utf-8"))
    report = args.output / "geo-acceptance-evidence.html"
    report.write_text(
        report_html(acceptance=acceptance, browser=browser, backup=backup), encoding="utf-8"
    )
    with sync_playwright() as playwright:
        browser_instance = playwright.chromium.launch(headless=True)
        page = browser_instance.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(report.resolve().as_uri(), wait_until="networkidle")
        page.screenshot(path=str(args.output / "geo-acceptance-evidence.png"), full_page=True)
        browser_instance.close()
    print(f"acceptance evidence captured: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
