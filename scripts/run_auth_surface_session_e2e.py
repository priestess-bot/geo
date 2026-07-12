#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
ADMIN_APP = ROOT / "apps/admin-web"
CUSTOMER_APP = ROOT / "apps/customer-web"
ADMIN_PORT = 3310
CUSTOMER_PORT = 3320
RECOVERY_SECRET = "auth-web-contract-recovery-secret-0123456789abcdef"


def scope_for(kind: str) -> dict[str, Any]:
    if kind == "many":
        project_scopes = [
            {
                "project_id": f"customer-project-{index:03d}",
                "roles": ["client_viewer"],
                "permissions": ["project.read", "report.read"],
                "portal_capabilities": ["portal.customer.access"],
                "scope_sources": ["direct_member"],
            }
            for index in range(1, 202)
        ]
    else:
        project_scopes = [
            {
                "project_id": "project-b",
                "roles": ["client_viewer"],
                "permissions": ["project.read", "report.read"],
                "portal_capabilities": ["portal.customer.access"],
                "scope_sources": ["direct_member"],
            }
        ]
    if kind == "mixed":
        project_scopes.insert(
            0,
            {
                "project_id": "project-a",
                "roles": ["analyst"],
                "permissions": ["project.read"],
                "portal_capabilities": ["portal.admin.access"],
                "scope_sources": ["direct_member"],
            },
        )
    return {
        "scope_version": "runtime_session_scope_v2",
        "authz_policy_version": "auth_surface_policy_v1",
        "actor_id": f"{kind}@example.test",
        "tenant_id": "tenant-1",
        "tenant_roles": [],
        "project_scopes": project_scopes,
        "project_ids": [entry["project_id"] for entry in project_scopes],
    }


@dataclass
class Invitation:
    token: str
    role: str | None
    surfaces: tuple[str, ...]
    session_kind: str
    state: str = "pending"


@dataclass
class MockState:
    invitations: dict[str, Invitation] = field(default_factory=dict)
    ledgers: dict[tuple[str, str, str], tuple[str, tuple[str, str]]] = field(default_factory=dict)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    redeem_requests: list[dict[str, Any]] = field(default_factory=list)
    preflight_requests: list[dict[str, Any]] = field(default_factory=list)
    project_surfaces: list[str] = field(default_factory=list)
    project_queries: list[tuple[str, int, int]] = field(default_factory=list)
    confirmed_sessions: list[str] = field(default_factory=list)
    auth_me_cookie_headers: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self.lock:
            self.invitations = {
                "analyst-id": Invitation("analyst-secret", "analyst", ("admin",), "mixed"),
                "viewer-id": Invitation("viewer-secret", "client_viewer", ("customer",), "viewer"),
                "stale-id": Invitation("stale-secret", "analyst", (), "mixed", state="policy_stale"),
                "analyst-browser": Invitation("analyst-browser-secret", "analyst", ("admin",), "mixed"),
                "viewer-browser": Invitation("viewer-browser-secret", "client_viewer", ("customer",), "viewer"),
                "viewer-mobile": Invitation("viewer-mobile-secret", "client_viewer", ("customer",), "viewer"),
                "many-id": Invitation("many-secret", "client_viewer", ("customer",), "many"),
            }
            self.ledgers.clear()
            self.sessions.clear()
            self.redeem_requests.clear()
            self.preflight_requests.clear()
            self.project_surfaces.clear()
            self.project_queries.clear()
            self.confirmed_sessions.clear()
            self.auth_me_cookie_headers.clear()


STATE = MockState()
STATE.reset()


class MockAuthApiHandler(BaseHTTPRequestHandler):
    server_version = "GeoAuthContractMock/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        cookies: tuple[str, ...] = (),
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/v1/auth/invitations/preflight":
            self._preflight()
            return
        if path == "/v1/auth/invitations/redeem":
            self._redeem()
            return
        if path == "/v1/auth/logout":
            self._send_json(200, {"status": "logged_out"})
            return
        self._send_json(404, {"code": "not_found", "detail": "Not found", "correlation_id": "mock-404"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path == "/v1/auth/me":
            self._auth_me()
            return
        if parsed.path == "/v1/projects/runtime":
            self._projects(parse_qs(parsed.query))
            return
        if parsed.path.endswith("/runtime") or "/runtime/" in parsed.path:
            if parsed.path in {"/v1/project-launch-configs/runtime", "/v1/score-weight-configs/runtime"}:
                self._send_json(200, {})
            else:
                self._send_json(200, {"total_count": 0, "records": []})
            return
        self._send_json(404, {"code": "not_found", "detail": "Not found", "correlation_id": "mock-404"})

    def _preflight(self) -> None:
        payload = self._json_body()
        invitation_id = str(payload.get("invitation_id") or "")
        token = str(payload.get("invite_token") or "")
        surface = str(payload.get("requested_surface") or "")
        with STATE.lock:
            STATE.preflight_requests.append({"invitation_id": invitation_id, "surface": surface})
            invitation = STATE.invitations.get(invitation_id)
            if invitation_id == "stale-id" and invitation and invitation.token == token:
                compatibility = "policy_stale"
                recommended = None
                role = invitation.role
            elif not invitation or invitation.token != token or invitation.state != "pending":
                compatibility = "invalid"
                recommended = None
                role = None
            elif surface not in invitation.surfaces:
                compatibility = "surface_mismatch"
                recommended = invitation.surfaces[0]
                role = invitation.role
            else:
                compatibility = "compatible"
                recommended = surface
                role = invitation.role
        self._send_json(
            200,
            {
                "compatibility": compatibility,
                "requested_surface": surface,
                "recommended_surface": recommended,
                "invitation_role": role,
                "policy_version": "auth_surface_policy_v1",
                "correlation_id": f"preflight-{invitation_id or 'invalid'}",
            },
        )

    def _redeem(self) -> None:
        payload = self._json_body()
        invitation_id = str(payload.get("invitation_id") or "")
        token = str(payload.get("invite_token") or "")
        surface = str(payload.get("requested_surface") or "")
        key = str(self.headers.get("Idempotency-Key") or "")
        with STATE.lock:
            STATE.redeem_requests.append({"invitation_id": invitation_id, "surface": surface, "key": key})
            invitation = STATE.invitations.get(invitation_id)
            if not invitation or invitation.token != token:
                self._send_json(404, {"code": "invitation_invalid", "detail": "Invalid invitation", "correlation_id": "redeem-invalid"})
                return
            ledger_key = (invitation_id, surface, key)
            replay = STATE.ledgers.get(ledger_key)
            if replay:
                session_token, cookies = replay
                session = STATE.sessions[session_token]
                self._send_json(
                    200,
                    {"recovery_status": "replayed", "session": session, "correlation_id": "redeem-replayed"},
                    cookies=cookies,
                )
                return
            if invitation.state != "pending":
                self._send_json(409, {"code": "invitation_already_consumed", "detail": "Already consumed", "correlation_id": "redeem-consumed"})
                return
            if surface not in invitation.surfaces:
                self._send_json(
                    409,
                    {
                        "code": "invitation_surface_mismatch",
                        "detail": "This invitation cannot open the requested surface.",
                        "recommended_surface": invitation.surfaces[0],
                        "invitation_consumed": False,
                        "correlation_id": "redeem-mismatch",
                    },
                )
                return
            session_token = f"session-{invitation.session_kind}-{len(STATE.sessions) + 1}"
            csrf_token = f"csrf-{invitation.session_kind}-{len(STATE.sessions) + 1}"
            cookies = (
                f"GENO_RUNTIME_SESSION={session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800; Expires=Wed, 21 Oct 2037 07:28:00 GMT",
                f"GENO_CSRF_TOKEN={csrf_token}; Path=/; SameSite=Lax; Max-Age=604800; Expires=Wed, 21 Oct 2037 07:28:00 GMT",
            )
            session = scope_for(invitation.session_kind)
            STATE.sessions[session_token] = session
            STATE.ledgers[ledger_key] = (session_token, cookies)
            invitation.state = "accepted"
        self._send_json(
            200,
            {"recovery_status": "created", "session": session, "correlation_id": "redeem-created"},
            cookies=cookies,
        )

    def _auth_me(self) -> None:
        session_token = str(self.headers.get("X-GENO-Session-Token") or "")
        with STATE.lock:
            session = STATE.sessions.get(session_token)
            STATE.auth_me_cookie_headers.append(str(self.headers.get("Cookie") or ""))
            if session:
                STATE.confirmed_sessions.append(session_token)
        if not session:
            self._send_json(401, {"code": "auth_request_failed", "detail": "Session required", "correlation_id": "auth-me-401"})
            return
        self._send_json(200, {"session": session})

    def _projects(self, query: dict[str, list[str]]) -> None:
        session_token = str(self.headers.get("X-GENO-Session-Token") or "")
        surface = (query.get("surface") or [""])[0]
        project_id = (query.get("project_id") or [""])[0]
        limit = max(1, min(200, int((query.get("limit") or ["50"])[0])))
        offset = max(0, int((query.get("offset") or ["0"])[0]))
        with STATE.lock:
            session = STATE.sessions.get(session_token)
            STATE.project_surfaces.append(surface)
            STATE.project_queries.append((surface, offset, limit))
        if not session:
            self._send_json(401, {"code": "auth_request_failed", "detail": "Session required", "correlation_id": "projects-401"})
            return
        allowed = {
            scope["project_id"]
            for scope in session["project_scopes"]
            if f"portal.{surface}.access" in scope["portal_capabilities"]
        }
        projects: dict[str, dict[str, Any]] = {
            "project-a": {
                "project": {"id": "project-a", "name": "Admin Project Alpha", "target_brand": "Alpha", "status": "active"},
                "tenant": {"name": "Tenant One"},
                "competitors": [],
                "prompt_count": 3,
            },
            "project-b": {
                "project": {"id": "project-b", "name": "Customer Project Beta", "target_brand": "Beta", "status": "active"},
                "tenant": {"name": "Tenant One"},
                "competitors": [],
                "prompt_count": 2,
            },
        }
        for key in allowed:
            if key.startswith("customer-project-"):
                index = int(key.rsplit("-", 1)[-1])
                projects[key] = {
                    "project": {
                        "id": key,
                        "name": f"Customer Project {index:03d}",
                        "target_brand": f"Brand {index:03d}",
                        "status": "active",
                    },
                    "tenant": {"name": "Tenant One"},
                    "competitors": [],
                    "prompt_count": index,
                }
        matching_keys = [key for key in sorted(allowed) if not project_id or key == project_id]
        total_count = len(matching_keys)
        page_keys = matching_keys[offset : offset + limit]
        records = [projects[key] for key in page_keys]
        self._send_json(200, {"total_count": total_count, "limit": limit, "offset": offset, "records": records})


class BrowserClient:
    def __init__(self, port: int):
        self.port = port
        self.cookies: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        apply_cookies: bool = True,
    ) -> tuple[int, dict[str, list[str]], bytes]:
        headers = {"Accept": "application/json,text/html"}
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        connection = HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        response_headers: dict[str, list[str]] = {}
        for key, value in response.getheaders():
            response_headers.setdefault(key.lower(), []).append(value)
        connection.close()
        if apply_cookies:
            self._apply_set_cookies(response_headers.get("set-cookie", []))
        return response.status, response_headers, response_body

    def _apply_set_cookies(self, values: list[str]) -> None:
        for value in values:
            pair = value.split(";", 1)[0]
            if "=" not in pair:
                continue
            name, cookie_value = pair.split("=", 1)
            if "Max-Age=0" in value or not cookie_value:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = cookie_value


@dataclass
class NextProcess:
    process: subprocess.Popen[bytes]
    log: Any
    name: str

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.flush()

    def log_tail(self) -> str:
        self.log.flush()
        self.log.seek(0)
        return self.log.read().decode("utf-8", errors="replace")[-6000:]


def start_next(name: str, app_dir: Path, port: int, env: dict[str, str]) -> NextProcess:
    executable = app_dir / "node_modules/.bin/next"
    if not executable.exists():
        raise RuntimeError(f"{name}: dependencies are missing; run npm ci in {app_dir}")
    log = tempfile.TemporaryFile()
    process = subprocess.Popen(
        [str(executable), "dev", "-H", "127.0.0.1", "-p", str(port)],
        cwd=app_dir,
        env={**os.environ, **env},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return NextProcess(process=process, log=log, name=name)


def wait_ready(process: NextProcess, port: int, path: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise RuntimeError(f"{process.name} exited before ready:\n{process.log_tail()}")
        try:
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", path)
            response: HTTPResponse = connection.getresponse()
            response.read()
            connection.close()
            if response.status < 500:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{process.name} did not become ready:\n{process.log_tail()}")


def json_body(body: bytes) -> dict[str, Any]:
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise AssertionError("expected a JSON object")
    return parsed


def session_cookie_headers(headers: dict[str, list[str]]) -> tuple[str, ...]:
    return tuple(
        value
        for value in headers.get("set-cookie", [])
        if value.startswith("GENO_RUNTIME_SESSION=") or value.startswith("GENO_CSRF_TOKEN=")
    )


def location_path(headers: dict[str, list[str]]) -> str:
    locations = headers.get("location", [])
    if len(locations) != 1:
        return ""
    parsed = urlsplit(locations[0])
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def run_contract_checks() -> dict[str, Any]:
    STATE.reset()
    admin = BrowserClient(ADMIN_PORT)
    customer = BrowserClient(CUSTOMER_PORT)

    status, _, body = admin.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "unknown", "invite_token": "unknown", "return_url": "https://evil.test/"},
    )
    assert status == 409, (status, body)
    assert json_body(body)["code"] == "invitation_invalid"

    status, _, body = admin.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "stale-id", "invite_token": "stale-secret"},
    )
    assert status == 409, (status, body)
    assert json_body(body)["code"] == "invitation_policy_stale"

    with STATE.lock:
        redeem_count = len(STATE.redeem_requests)
    status, _, body = admin.request(
        "POST",
        "/api/auth/login",
        {"invitation_id": "analyst-id", "invite_token": "analyst-secret"},
    )
    assert status == 428, (status, body)
    assert json_body(body)["code"] == "redeem_prepare_required"
    with STATE.lock:
        assert len(STATE.redeem_requests) == redeem_count

    viewer_admin = BrowserClient(ADMIN_PORT)
    with STATE.lock:
        redeem_count = len(STATE.redeem_requests)
    status, headers, body = viewer_admin.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "viewer-id", "invite_token": "viewer-secret"},
    )
    mismatch = json_body(body)
    assert status == 409, (status, body)
    assert mismatch["code"] == "invitation_surface_mismatch"
    assert mismatch["recommended_surface"] == "customer"
    assert mismatch["correlation_id"]
    assert not headers.get("set-cookie")
    with STATE.lock:
        assert len(STATE.redeem_requests) == redeem_count
        assert STATE.invitations["viewer-id"].state == "pending"

    status, headers, body = admin.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "analyst-id", "invite_token": "analyst-secret"},
    )
    assert status == 200, (status, body)
    assert json_body(body)["prepared"] is True
    recovery_cookie = admin.cookies.get("GENO_ADMIN_REDEEM_RECOVERY")
    assert recovery_cookie and "analyst-secret" not in recovery_cookie
    assert any(
        "httponly" in value.lower()
        and "samesite=lax" in value.lower()
        and "max-age=600" in value.lower()
        for value in headers["set-cookie"]
    ), headers

    login_payload = {
        "invitation_id": "analyst-id",
        "invite_token": "analyst-secret",
        "return_url": "https://evil.test/steal",
    }
    status, first_headers, _ = admin.request("POST", "/api/auth/login", login_payload, apply_cookies=False)
    assert status == 303
    assert location_path(first_headers) == "/projects", first_headers
    first_delivery = session_cookie_headers(first_headers)
    assert len(first_delivery) == 2, first_headers

    with STATE.lock:
        preflight_count = len(STATE.preflight_requests)
    recovery_before_refresh = admin.cookies["GENO_ADMIN_REDEEM_RECOVERY"]
    status, refreshed_prepare_headers, body = admin.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "analyst-id", "invite_token": "analyst-secret"},
    )
    assert status == 200, (status, body)
    assert json_body(body)["prepared"] is True
    assert admin.cookies["GENO_ADMIN_REDEEM_RECOVERY"] == recovery_before_refresh
    assert not refreshed_prepare_headers.get("set-cookie")
    with STATE.lock:
        assert len(STATE.preflight_requests) == preflight_count

    status, second_headers, _ = admin.request("POST", "/api/auth/login", login_payload)
    assert status == 303
    assert location_path(second_headers) == "/projects", second_headers
    second_delivery = session_cookie_headers(second_headers)
    assert second_delivery == first_delivery
    with STATE.lock:
        analyst_keys = [
            entry["key"] for entry in STATE.redeem_requests if entry["invitation_id"] == "analyst-id"
        ]
    assert len(analyst_keys) == 2 and len(set(analyst_keys)) == 1

    status, _, body = admin.request("GET", "/projects")
    text = body.decode("utf-8")
    assert status == 200
    assert "Admin Project Alpha" in text
    assert "Customer Project Beta" not in text
    with STATE.lock:
        assert "admin" in STATE.project_surfaces

    partial_delivery = BrowserClient(ADMIN_PORT)
    partial_delivery.cookies["GENO_ADMIN_REDEEM_RECOVERY"] = admin.cookies["GENO_ADMIN_REDEEM_RECOVERY"]
    partial_delivery.cookies["GENO_RUNTIME_SESSION"] = admin.cookies["GENO_RUNTIME_SESSION"]
    with STATE.lock:
        auth_me_count = len(STATE.auth_me_cookie_headers)
    status, headers, body = partial_delivery.request("POST", "/api/auth/session-confirm")
    assert status == 409, (status, body)
    assert json_body(body)["code"] == "auth_session_delivery_invalid"
    assert "GENO_ADMIN_REDEEM_RECOVERY" in partial_delivery.cookies
    assert not any("GENO_ADMIN_REDEEM_RECOVERY=" in value for value in headers.get("set-cookie", []))
    with STATE.lock:
        assert len(STATE.auth_me_cookie_headers) == auth_me_count

    status, confirm_headers, body = admin.request("POST", "/api/auth/session-confirm")
    assert status == 200, (status, body)
    assert json_body(body)["session"]["scope_version"] == "runtime_session_scope_v2"
    assert any("GENO_ADMIN_REDEEM_RECOVERY=" in value and "Max-Age=0" in value for value in confirm_headers["set-cookie"])
    assert "GENO_ADMIN_REDEEM_RECOVERY" not in admin.cookies
    with STATE.lock:
        confirm_cookie_header = STATE.auth_me_cookie_headers[-1]
    assert "GENO_RUNTIME_SESSION=" in confirm_cookie_header
    assert "GENO_CSRF_TOKEN=" in confirm_cookie_header
    assert "REDEEM_RECOVERY" not in confirm_cookie_header

    invalid_scope_client = BrowserClient(ADMIN_PORT)
    status, _, body = invalid_scope_client.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "analyst-browser", "invite_token": "analyst-browser-secret"},
    )
    assert status == 200, (status, body)
    invalid_scope = scope_for("mixed")
    invalid_scope["project_ids"] = []
    with STATE.lock:
        STATE.sessions["invalid-scope-session"] = invalid_scope
    invalid_scope_client.cookies["GENO_RUNTIME_SESSION"] = "invalid-scope-session"
    invalid_scope_client.cookies["GENO_CSRF_TOKEN"] = "invalid-scope-csrf"
    status, headers, body = invalid_scope_client.request("POST", "/api/auth/session-confirm")
    assert status == 502, (status, body)
    assert json_body(body)["code"] == "auth_session_delivery_invalid"
    assert "GENO_ADMIN_REDEEM_RECOVERY" in invalid_scope_client.cookies
    assert not any("GENO_ADMIN_REDEEM_RECOVERY=" in value for value in headers.get("set-cookie", []))

    status, _, body = customer.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "viewer-id", "invite_token": "viewer-secret"},
    )
    assert status == 200, (status, body)
    status, headers, _ = customer.request(
        "POST",
        "/api/auth/login",
        {"invitation_id": "viewer-id", "invite_token": "viewer-secret", "return_url": "https://evil.test/"},
    )
    assert status == 303
    assert location_path(headers) == "/", headers
    with STATE.lock:
        assert STATE.invitations["viewer-id"].state == "accepted"

    status, _, body = customer.request("GET", "/")
    text = body.decode("utf-8")
    assert status == 200
    assert "Customer Project Beta" in text
    assert "Admin Project Alpha" not in text
    assert "viewer-secret" not in text
    with STATE.lock:
        assert "customer" in STATE.project_surfaces

    mixed_customer = BrowserClient(CUSTOMER_PORT)
    mixed_customer.cookies["GENO_RUNTIME_SESSION"] = admin.cookies["GENO_RUNTIME_SESSION"]
    mixed_customer.cookies["GENO_CSRF_TOKEN"] = admin.cookies["GENO_CSRF_TOKEN"]
    status, _, body = mixed_customer.request("GET", "/")
    text = body.decode("utf-8")
    assert status == 200
    assert "Customer Project Beta" in text
    assert "Admin Project Alpha" not in text

    many_customer = BrowserClient(CUSTOMER_PORT)
    status, _, body = many_customer.request(
        "POST",
        "/api/auth/redeem-prepare",
        {"invitation_id": "many-id", "invite_token": "many-secret"},
    )
    assert status == 200, (status, body)
    status, _, body = many_customer.request(
        "POST",
        "/api/auth/login",
        {"invitation_id": "many-id", "invite_token": "many-secret"},
    )
    assert status == 303, (status, body)
    status, _, body = many_customer.request("GET", "/?project_id=customer-project-201")
    text = body.decode("utf-8")
    assert status == 200
    assert "Customer Project 201" in text
    assert 'value="customer-project-201"' in text
    with STATE.lock:
        assert ("customer", 0, 200) in STATE.project_queries
        assert ("customer", 200, 200) in STATE.project_queries

    return {
        "checks": 36,
        "admin_surface_projection": True,
        "customer_surface_projection": True,
        "stable_replay_key": analyst_keys[0],
    }


def run_playwright_checks() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Python Playwright is unavailable") from exc

    STATE.reset()
    screenshot_dir = Path(tempfile.mkdtemp(prefix="geo-auth-web-playwright-"))
    console_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        admin_context = browser.new_context(viewport={"width": 1440, "height": 900})
        admin_page = admin_context.new_page()
        admin_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        admin_page.goto(
            f"http://127.0.0.1:{ADMIN_PORT}/login?invitation_id=viewer-browser",
            wait_until="networkidle",
        )
        assert admin_page.title()
        assert admin_page.locator("h1").inner_text() == "内部用户登录"
        assert admin_page.get_by_label("邀请 ID").input_value() == "viewer-browser"
        admin_page.get_by_label("一次性邀请 token").fill("viewer-browser-secret")
        admin_page.get_by_role("button", name="兑换邀请并登录").click()
        recommended_link = admin_page.get_by_role("link", name="前往客户门户")
        recommended_link.wait_for()
        recommended_href = recommended_link.get_attribute("href") or ""
        assert "invitation_id=viewer-browser" in recommended_href
        assert "invite_token" not in recommended_href
        assert "viewer-browser-secret" not in recommended_href
        assert "viewer-browser-secret" not in admin_page.url
        mismatch_shot = screenshot_dir / "admin-surface-mismatch.png"
        admin_page.screenshot(path=str(mismatch_shot), full_page=False)
        with STATE.lock:
            assert not [item for item in STATE.redeem_requests if item["invitation_id"] == "viewer-browser"]

        admin_page.get_by_label("邀请 ID").fill("analyst-browser")
        admin_page.get_by_label("一次性邀请 token").fill("analyst-browser-secret")
        admin_page.get_by_role("button", name="兑换邀请并登录").click()
        admin_page.wait_for_url(f"http://127.0.0.1:{ADMIN_PORT}/projects", wait_until="networkidle")
        admin_page.get_by_text("Admin Project Alpha").wait_for()
        assert admin_page.get_by_text("Customer Project Beta").count() == 0
        admin_shot = screenshot_dir / "admin-desktop.png"
        admin_page.screenshot(path=str(admin_shot), full_page=False)
        admin_context.close()

        customer_context = browser.new_context(viewport={"width": 390, "height": 844})
        customer_page = customer_context.new_page()
        customer_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        customer_page.goto(f"http://127.0.0.1:{CUSTOMER_PORT}/?invitation_id=viewer-mobile", wait_until="networkidle")
        customer_page.get_by_label("一次性邀请 token").fill("viewer-mobile-secret")
        customer_page.get_by_role("button", name="兑换邀请并登录").click()
        customer_page.wait_for_url(f"http://127.0.0.1:{CUSTOMER_PORT}/", wait_until="networkidle")
        customer_page.get_by_text("Customer Project Beta").first.wait_for()
        assert "viewer-mobile-secret" not in customer_page.url
        customer_shot = screenshot_dir / "customer-mobile.png"
        customer_page.screenshot(path=str(customer_shot), full_page=False)
        customer_context.close()
        browser.close()

    expected_console_events = [
        message for message in console_errors
        if "Failed to load resource" in message and "409" in message
    ]
    unexpected_console_errors = [message for message in console_errors if message not in expected_console_events]
    assert not unexpected_console_errors, unexpected_console_errors
    return {
        "desktop": str(admin_shot),
        "surface_mismatch": str(mismatch_shot),
        "mobile": str(customer_shot),
        "console_errors": unexpected_console_errors,
        "expected_console_events": expected_console_events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auth surface/session BFF contract E2E")
    parser.add_argument("--contract-only", action="store_true", help="Run HTTP contract checks without a browser")
    parser.add_argument("--browser", action="store_true", help="Also run regular Playwright desktop/mobile checks")
    args = parser.parse_args()

    secret_file = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
    secret_file.write(RECOVERY_SECRET + "\n")
    secret_file.close()
    mock = ThreadingHTTPServer(("127.0.0.1", 0), MockAuthApiHandler)
    mock_port = int(mock.server_address[1])
    mock_thread = threading.Thread(target=mock.serve_forever, daemon=True)
    mock_thread.start()
    common = {
        "API_INTERNAL_BASE_URL": f"http://127.0.0.1:{mock_port}",
        "GENO_RUNTIME_AUTH_MODE": "session",
        "GENO_RUNTIME_SESSION_COOKIE_SECURE": "0",
        "NEXT_TELEMETRY_DISABLED": "1",
    }
    admin = start_next(
        "admin-web",
        ADMIN_APP,
        ADMIN_PORT,
        {
            **common,
            "GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE": secret_file.name,
            "CUSTOMER_WEB_BASE_URL": f"http://127.0.0.1:{CUSTOMER_PORT}/",
        },
    )
    customer = start_next(
        "customer-web",
        CUSTOMER_APP,
        CUSTOMER_PORT,
        {
            **common,
            "GENO_AUTH_RECOVERY_COOKIE_SECRET": RECOVERY_SECRET,
            "ADMIN_WEB_BASE_URL": f"http://127.0.0.1:{ADMIN_PORT}/login",
        },
    )
    try:
        wait_ready(admin, ADMIN_PORT, "/login")
        wait_ready(customer, CUSTOMER_PORT, "/")
        result: dict[str, Any] = {"contract": run_contract_checks()}
        if args.browser and not args.contract_only:
            result["playwright"] = run_playwright_checks()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception:
        print(f"\n--- admin-web log ---\n{admin.log_tail()}")
        print(f"\n--- customer-web log ---\n{customer.log_tail()}")
        raise
    finally:
        customer.stop()
        admin.stop()
        mock.shutdown()
        mock.server_close()
        mock_thread.join(timeout=5)
        Path(secret_file.name).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
