"""Production Playwright adapter for authorized, bounded Style Collection."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import zipfile

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from geo_core.secrets.models import SecretValue
from geo_core.synthetic_lab.application_support import canonical_hash
from geo_core.synthetic_lab.collection_execution_contracts import (
    CollectionBlockReason,
    NavigationGuard,
    RobotsAccessDecision,
    StyleCollectionExecutionError,
    StyleCollectionTask,
    StylePageCapture,
)
from geo_core.synthetic_lab.domain import StyleAccessMode
from geo_core.synthetic_lab.style_browser import StyleAdapterRegistry, StyleAdapterRelease


_CREDENTIAL_QUERY_NAMES = frozenset(
    {"access_token", "api_key", "authorization", "password", "session", "session_token"}
)
_BLOCK_PATTERNS = {
    CollectionBlockReason.CAPTCHA: ("captcha", "verify you are human", "recaptcha"),
    CollectionBlockReason.RATE_LIMITED: ("too many requests", "rate limit"),
    CollectionBlockReason.ACCESS_DENIED: ("access denied", "request blocked", "forbidden"),
}
_SENSITIVE_HAR_KEYS = frozenset(
    {"authorization", "cookie", "set-cookie", "postdata", "querystring", "cookies"}
)
_FORM_SCRUB_SCRIPT = """
elements => elements.forEach(element => {
  if (element.tagName === 'SELECT') element.selectedIndex = -1;
  else element.value = '';
  if (element.tagName === 'TEXTAREA') element.textContent = '';
  for (const attribute of Array.from(element.attributes)) {
    const name = attribute.name.toLowerCase();
    if (['value', 'checked', 'selected', 'name', 'id', 'autocomplete', 'formaction'].includes(name)
        || /password|token|session|auth|cookie/.test(name)) {
      element.removeAttribute(attribute.name);
    }
  }
})
""".strip()


class PlaywrightStyleCollector:
    def __init__(
        self,
        *,
        registry: StyleAdapterRegistry,
        chromium_executable: str,
        allowed_egress_hosts: tuple[str, ...],
        browser_ws_endpoint: str | None = None,
        http_client: httpx.Client | None = None,
        playwright_factory: Callable[[], AbstractContextManager[Any]] = sync_playwright,
        clock: Callable[[], datetime] | None = None,
        allow_reviewed_fixture: bool = False,
    ) -> None:
        self._registry = registry
        self._chromium = chromium_executable
        self._browser_ws_endpoint = browser_ws_endpoint
        self._allowed_egress_hosts = frozenset(
            host.lower().strip() for host in allowed_egress_hosts if host.strip()
        )
        if not self._allowed_egress_hosts:
            raise StyleCollectionExecutionError("Style browser egress allowlist is empty")
        self._http = http_client or httpx.Client(
            follow_redirects=False,
            timeout=10,
            trust_env=False,
        )
        self._playwright_factory = playwright_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._allow_reviewed_fixture = allow_reviewed_fixture

    def check_robots(self, task: StyleCollectionTask, url: str) -> RobotsAccessDecision:
        self._assert_egress(task, url)
        parsed = urlsplit(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = self._http.get(
            robots_url,
            headers={"User-Agent": task.robots_user_agent, "Accept": "text/plain"},
        )
        if response.status_code in {404, 410}:
            allowed, body = True, b""
        elif response.status_code == 200 and len(response.content) <= 1_048_576:
            body = response.content
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(body.decode("utf-8", errors="replace").splitlines())
            allowed = parser.can_fetch(task.robots_user_agent, url)
        else:
            allowed, body = False, response.content[:1_048_576]
        return RobotsAccessDecision(
            allowed=allowed,
            checked_at=self._clock(),
            policy_hash=canonical_hash(
                {
                    "robots_url": robots_url,
                    "status_code": response.status_code,
                    "body_hash": hashlib.sha256(body).hexdigest(),
                    "allowed": allowed,
                }
            ),
        )

    def collect(
        self,
        task: StyleCollectionTask,
        *,
        credential: SecretValue | None,
        before_navigation: NavigationGuard,
    ) -> StylePageCapture:
        adapter = self._registry.require(
            task,
            allow_reviewed_fixture=self._allow_reviewed_fixture,
        )
        release_hosts = set(task.allowed_redirect_hosts) | set(adapter.allowed_resource_hosts)
        if not release_hosts.issubset(self._allowed_egress_hosts):
            raise StyleCollectionExecutionError("Style task exceeds worker egress allowlist")
        username, password = _login_credential(task, credential)
        with self._playwright_factory() as playwright:
            browser = (
                playwright.chromium.connect(self._browser_ws_endpoint)
                if self._browser_ws_endpoint is not None
                else playwright.chromium.launch(
                    headless=True,
                    executable_path=self._chromium,
                )
            )
            try:
                return self._capture(
                    browser,
                    task=task,
                    adapter=adapter,
                    username=username,
                    password=password,
                    before_navigation=before_navigation,
                )
            finally:
                browser.close()

    def _assert_egress(self, task: StyleCollectionTask, url: str) -> None:
        host = (urlsplit(url).hostname or "").lower()
        if host not in task.allowed_redirect_hosts or host not in self._allowed_egress_hosts:
            raise StyleCollectionExecutionError("Style request exceeds frozen egress allowlists")

    def _capture(
        self,
        browser: Any,
        *,
        task: StyleCollectionTask,
        adapter: StyleAdapterRelease,
        username: str | None,
        password: str | None,
        before_navigation: NavigationGuard,
    ) -> StylePageCapture:
        spool = Path(task.tmpfs.mount_path)
        spool.mkdir(parents=True, exist_ok=True)
        har_path = spool / f"{task.collection_run_id}-{task.job_id}.har"
        context = browser.new_context(
            accept_downloads=False,
            locale="en-AU",
            timezone_id="Australia/Sydney",
            user_agent=task.robots_user_agent,
            service_workers="block",
            record_har_path=str(har_path),
            record_har_content="omit",
            viewport={"width": 1440, "height": 900},
        )
        navigation_chain: list[str] = []
        guard_error: list[BaseException] = []
        allowed_request_hosts = set(task.allowed_redirect_hosts) | set(
            adapter.allowed_resource_hosts
        )

        def guard_route(route: Any) -> None:
            request = route.request
            try:
                _assert_request_url(request.url, allowed_request_hosts)
                if request.is_navigation_request() and request.resource_type == "document":
                    before_navigation(request.url)
                    navigation_chain.append(request.url)
            except BaseException as error:
                guard_error.append(error)
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", guard_route)
        context.route_web_socket("**/*", lambda socket: socket.close())
        page = context.new_page()
        page.set_default_timeout(adapter.navigation_timeout_ms)
        page.set_default_navigation_timeout(adapter.navigation_timeout_ms)
        block_reason: CollectionBlockReason | None = None
        context_closed = False
        try:
            try:
                if adapter.login_flow is not None:
                    flow = adapter.login_flow
                    response = page.goto(flow.login_url, wait_until="domcontentloaded")
                    block_reason = _response_block(response) or _page_block(page)
                    if block_reason is None:
                        page.locator(flow.username_selector).fill(username or "")
                        page.locator(flow.password_selector).fill(password or "")
                        page.locator(flow.submit_selector).click()
                        try:
                            page.locator(flow.success_selector).wait_for(state="visible")
                        except PlaywrightTimeoutError:
                            block_reason = _page_block(page) or CollectionBlockReason.LOGIN_FAILED
                if block_reason is None:
                    response = page.goto(task.source_url, wait_until="domcontentloaded")
                    if adapter.settle_timeout_ms:
                        page.wait_for_timeout(adapter.settle_timeout_ms)
                    block_reason = _response_block(response) or _page_block(page)
            except PlaywrightError:
                if guard_error:
                    raise guard_error[0]
                raise
            if guard_error:
                raise guard_error[0]
            final_url = page.url
            controls = page.locator("input, textarea, select")
            screenshot = page.screenshot(
                type="png",
                full_page=False,
                animations="disabled",
                mask=[controls],
                mask_color="#000000",
            )
            controls.evaluate_all(_FORM_SCRUB_SCRIPT)
            dom = page.content().encode("utf-8")
            records = _content_records(page, adapter.content_selectors)
            context.close()
            context_closed = True
            har = _sanitized_har(har_path, task.tmpfs.maximum_bytes)
            bundle = _capture_bundle(
                dom=dom,
                screenshot=screenshot,
                har=har,
                records=records,
                maximum_bytes=task.tmpfs.maximum_bytes,
            )
            return StylePageCapture(
                final_url=final_url,
                navigation_chain=tuple(navigation_chain),
                raw_bundle=bundle,
                raw_media_type="application/zip",
                captured_at=self._clock(),
                capture_release=f"{self._registry.release_id}:{adapter.release_hash}",
                block_reason=block_reason,
            )
        finally:
            if not context_closed:
                try:
                    context.close()
                except Exception:
                    pass
            har_path.unlink(missing_ok=True)


def _login_credential(
    task: StyleCollectionTask,
    credential: SecretValue | None,
) -> tuple[str | None, str | None]:
    if task.access_mode is StyleAccessMode.PUBLIC:
        if credential is not None:
            raise StyleCollectionExecutionError("public collector received a credential")
        return None, None
    if credential is None:
        raise StyleCollectionExecutionError("authenticated collector has no credential")
    try:
        value = json.loads(credential.reveal_text())
    except (ValueError, json.JSONDecodeError) as error:
        raise StyleCollectionExecutionError("login credential schema is invalid") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "username", "password"}
        or value["schema_version"] != 1
        or not isinstance(value["username"], str)
        or not isinstance(value["password"], str)
        or not value["username"]
        or not value["password"]
    ):
        raise StyleCollectionExecutionError("login credential schema is invalid")
    return value["username"], value["password"]


def _response_block(response: Any | None) -> CollectionBlockReason | None:
    status = getattr(response, "status", None)
    if status == 429:
        return CollectionBlockReason.RATE_LIMITED
    if status in {401, 403}:
        return CollectionBlockReason.ACCESS_DENIED
    return None


def _page_block(page: Any) -> CollectionBlockReason | None:
    try:
        text = page.locator("body").inner_text(timeout=2_000).lower()[:200_000]
    except PlaywrightError:
        return None
    for reason, patterns in _BLOCK_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            return reason
    return None


def _content_records(page: Any, selectors: tuple[str, ...]) -> list[str]:
    records: list[str] = []
    for selector in selectors:
        for value in page.locator(selector).all_inner_texts():
            normalized = " ".join(value.split())
            if normalized and normalized not in records:
                records.append(normalized)
            if len(records) >= 2_000:
                return records
    return records


def _sanitized_har(path: Path, maximum_bytes: int) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise StyleCollectionExecutionError("Style capture HAR is unavailable") from error
    if len(raw) > maximum_bytes:
        raise StyleCollectionExecutionError("Style capture HAR exceeds the frozen byte limit")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StyleCollectionExecutionError("Style capture HAR is invalid") from error
    sanitized = _sanitize_har_value(value)
    return json.dumps(sanitized, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def _sanitize_har_value(value: object, *, key: str = "") -> object:
    if key.lower() in _SENSITIVE_HAR_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        header_name = value.get("name")
        if isinstance(header_name, str) and header_name.lower() in _SENSITIVE_HAR_KEYS:
            return {"name": "[REDACTED]", "value": "[REDACTED]"}
        return {str(name): _sanitize_har_value(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_har_value(item) for item in value]
    if isinstance(value, str) and key.lower() == "url":
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return "[REDACTED]"


def _capture_bundle(
    *,
    dom: bytes,
    screenshot: bytes,
    har: bytes,
    records: list[str],
    maximum_bytes: int,
) -> bytearray:
    record_bytes = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode()
    for value in (dom, screenshot, har, record_bytes):
        if len(value) > maximum_bytes:
            raise StyleCollectionExecutionError("Style capture component exceeds byte limit")
    output = BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, value in (
            ("page.html", dom),
            ("viewport.png", screenshot),
            ("network.har.json", har),
            ("style-records.json", record_bytes),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, value)
    result = output.getvalue()
    if len(result) > maximum_bytes:
        raise StyleCollectionExecutionError("Style capture bundle exceeds byte limit")
    return bytearray(result)


def _assert_request_url(value: str, allowed_hosts: set[str]) -> None:
    parsed = urlsplit(value)
    query_names = {name.lower() for name, _item in parse_qsl(parsed.query, keep_blank_values=True)}
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or query_names.intersection(_CREDENTIAL_QUERY_NAMES)
    ):
        raise StyleCollectionExecutionError("Style browser request exceeded egress policy")


__all__ = ["PlaywrightStyleCollector"]
