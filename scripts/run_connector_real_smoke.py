from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_PATH = ROOT / "deepseek_api_key.txt"
DEFAULT_OUTPUT_PATH = ROOT / "tmp/connector-real-smoke/latest.json"
DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"

PROMPTS = (
    "Answer in one sentence: what makes a brand visible in AI search answers?",
    "Answer in two bullets: which evidence signals support an AI visibility score?",
    "Answer in one sentence: why do citations matter in a GEO report?",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_key(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"DeepSeek API key file not found: {path}")
    key = path.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError(f"DeepSeek API key file is empty: {path}")
    return key


def _redacted_response(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message") if isinstance(first_choice.get("message"), dict) else {}
    content_value = message.get("content")
    if isinstance(content_value, str):
        content = content_value
    elif isinstance(content_value, list):
        parts: list[str] = []
        for item in content_value:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        content = "\n".join(parts)
    else:
        content = ""
    if not content and isinstance(message.get("reasoning_content"), str):
        content = str(message["reasoning_content"])
    finish_reason = first_choice.get("finish_reason")
    return {
        "id": payload.get("id"),
        "model": payload.get("model"),
        "finish_reason": finish_reason,
        "answer_length": len(content),
        "answer_hash": _sha256_text(content) if content else None,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
    }


def run_smoke(*, key_path: Path, output_path: Path, endpoint: str, model: str, timeout_seconds: float) -> dict[str, Any]:
    api_key = _read_key(key_path)
    started_at = datetime.now(UTC)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    client = httpx.Client(timeout=timeout_seconds)
    try:
        for index, prompt in enumerate(PROMPTS, start=1):
            request_started = time.perf_counter()
            response = client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a concise GEO production smoke-test assistant.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": 320,
                },
            )
            latency_ms = round((time.perf_counter() - request_started) * 1000)
            status_ok = response.status_code == 200
            payload: dict[str, Any]
            try:
                payload = response.json()
            except ValueError:
                payload = {"non_json_body_sha256": _sha256_text(response.text)}
            redacted = _redacted_response(payload)
            answer_ok = bool(redacted.get("answer_length")) and redacted.get("finish_reason") != "length"
            model_ok = str(redacted.get("model") or model).startswith("deepseek-")
            check = {
                "name": f"deepseek_prompt_{index}",
                "status": "pass" if status_ok and answer_ok and model_ok else "fail",
                "provider": "deepseek",
                "endpoint": endpoint,
                "model": model,
                "http_status": response.status_code,
                "latency_ms": latency_ms,
                "request_prompt_sha256": _sha256_text(prompt),
                "response": redacted,
            }
            checks.append(check)
            if check["status"] != "pass":
                failures.append(
                    f"prompt_{index}: status={response.status_code}, answer_length={redacted.get('answer_length')}"
                )
    finally:
        client.close()

    report = {
        "status": "passed" if not failures else "failed",
        "provider": "deepseek",
        "endpoint": endpoint,
        "model": model,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "key_source": str(key_path.relative_to(ROOT)) if key_path.is_relative_to(ROOT) else str(key_path),
        "key_sha256_prefix": _sha256_text(api_key)[:12],
        "checks": checks,
        "summary": {
            "pass": sum(1 for check in checks if check["status"] == "pass"),
            "fail": len(failures),
            "prompt_count": len(PROMPTS),
        },
        "failure_reasons": failures,
    }
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if api_key and api_key in serialized:
        raise AssertionError("connector real smoke report contains the raw API key")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real DeepSeek connector smoke test without leaking secrets.")
    parser.add_argument("--key-path", default=str(DEFAULT_KEY_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=float, default=45)
    args = parser.parse_args()
    report = run_smoke(
        key_path=Path(args.key_path),
        output_path=Path(args.output_path),
        endpoint=args.endpoint,
        model=args.model,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "provider": report["provider"],
                "model": report["model"],
                "output_path": args.output_path,
                "summary": report["summary"],
                "failure_reasons": report["failure_reasons"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
