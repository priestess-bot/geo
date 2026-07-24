from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
import zipfile

import httpx
import pytest

from geo_style_worker.browser_adapter import PlaywrightStyleCollector
from geo_core.secrets.models import SecretValue, SecretVersionHandle
from geo_core.synthetic_lab.authorization import AuthorizationBinding
from geo_core.synthetic_lab.collection_execution_contracts import (
    ExtractedStyleText,
    StyleCollectionExecutionError,
    StylePageCapture,
    TmpfsCapturePolicy,
    StyleCollectionTask,
)
from geo_core.synthetic_lab.domain import STANDARD_STYLE_CHANNELS, StyleAccessMode
from geo_core.synthetic_lab.style_artifact_processing import (
    ConservativeStyleArtifactInspector,
    ZipStyleTextExtractor,
)
from geo_core.synthetic_lab.style_browser import load_style_adapter_registry
from geo_core.synthetic_lab.raw_artifact_governance import govern_raw_artifact


PROJECT_ID = UUID("50000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


def test_registry_requires_all_nine_channels_and_hashes_each_release(tmp_path) -> None:
    registry = load_style_adapter_registry(_registry_file(tmp_path))

    assert {channel for channel, _release in registry.adapters} == set(STANDARD_STYLE_CHANNELS)
    assert len(registry.registry_hash) == 64
    assert all(len(adapter.release_hash) == 64 for adapter in registry.adapters.values())


def test_live_collector_rejects_reviewed_fixture_release_by_default(tmp_path) -> None:
    registry = load_style_adapter_registry(_registry_file(tmp_path))
    task = SimpleNamespace(
        channel="amazon",
        adapter_release="style-amazon-v1",
        access_mode=StyleAccessMode.PUBLIC,
    )

    with pytest.raises(StyleCollectionExecutionError, match="no approved live canary"):
        registry.require(task)  # type: ignore[arg-type]

    adapter = registry.require(task, allow_reviewed_fixture=True)  # type: ignore[arg-type]
    assert adapter.admission_state.value == "reviewed_fixture"


@pytest.mark.parametrize("hosts", [["cdn.example", "cdn.example"], ["bad..example"]])
def test_registry_rejects_duplicate_or_invalid_resource_hosts(tmp_path, hosts) -> None:
    path = _registry_file(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["adapters"][0]["allowed_resource_hosts"] = hosts
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StyleCollectionExecutionError, match="resource hosts"):
        load_style_adapter_registry(path)


def test_robots_parser_is_fail_closed_and_uses_frozen_user_agent(tmp_path) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")

    collector = PlaywrightStyleCollector(
        registry=load_style_adapter_registry(_registry_file(tmp_path)),
        chromium_executable="/fixture/chromium",
        allowed_egress_hosts=("reviews.example", "login.example"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        clock=lambda: NOW,
    )
    task = _task(tmp_path, access_mode=StyleAccessMode.PUBLIC)

    denied = collector.check_robots(task, "https://reviews.example/private/page")
    allowed = collector.check_robots(task, "https://reviews.example/public/page")

    assert denied.allowed is False
    assert allowed.allowed is True
    assert all(request.url.path == "/robots.txt" for request in requests)
    assert requests[0].headers["User-Agent"] == task.robots_user_agent


def test_normal_login_guards_redirects_and_never_bundles_credentials(tmp_path) -> None:
    runtime = _FakePlaywright()
    collector = PlaywrightStyleCollector(
        registry=load_style_adapter_registry(_registry_file(tmp_path)),
        chromium_executable="/fixture/chromium",
        allowed_egress_hosts=("reviews.example", "login.example"),
        playwright_factory=lambda: runtime,
        clock=lambda: NOW,
    )
    task = _task(tmp_path, access_mode=StyleAccessMode.AUTHENTICATED)
    guarded: list[str] = []
    credential = SecretValue(
        json.dumps(
            {"schema_version": 1, "username": "operator@example.test", "password": "S3cret!"}
        )
    )

    capture = collector.collect(
        task,
        credential=credential,
        before_navigation=guarded.append,
    )

    assert guarded == [
        "https://login.example/sign-in",
        "https://reviews.example/start",
        "https://reviews.example/final",
    ]
    assert capture.navigation_chain == tuple(guarded)
    assert capture.final_url == guarded[-1]
    assert capture.raw_bundle is not None
    assert b"S3cret!" not in capture.raw_bundle
    assert b"operator@example.test" not in capture.raw_bundle
    with zipfile.ZipFile(io.BytesIO(capture.raw_bundle)) as bundle:
        har = bundle.read("network.har.json")
        records = json.loads(bundle.read("style-records.json"))
    assert b"S3cret!" not in har
    assert b"Bearer credential" not in har
    assert b"sid=credential" not in har
    assert records == ["Useful Australian review"]
    assert runtime.browser.launch_kwargs == {
        "headless": True,
        "executable_path": "/fixture/chromium",
    }
    assert "proxy" not in runtime.browser.launch_kwargs
    assert runtime.browser.last_context is not None
    assert runtime.browser.last_context.web_socket_closed is True

    extracted = ZipStyleTextExtractor().extract(task, capture)
    raw = ConservativeStyleArtifactInspector().inspect_raw(task, capture)
    derived = ConservativeStyleArtifactInspector().inspect_derived(task, capture, extracted)
    assert extracted.record_count == 1
    assert [item.value for item in raw.inspection.detected_findings] == ["restricted_content"]
    assert raw.inspection.unresolved_findings == ()
    assert derived.inspection.anonymization_verified is True
    assert derived.inspection.unresolved_findings == ()


def test_subresource_outside_release_task_and_worker_allowlists_is_aborted(tmp_path) -> None:
    runtime = _FakePlaywright()
    runtime.browser.subresource_url = "https://unapproved.example/tracker.js"
    collector = PlaywrightStyleCollector(
        registry=load_style_adapter_registry(_registry_file(tmp_path)),
        chromium_executable="/fixture/chromium",
        allowed_egress_hosts=("reviews.example", "login.example"),
        playwright_factory=lambda: runtime,
        clock=lambda: NOW,
    )

    with pytest.raises(StyleCollectionExecutionError, match="egress policy"):
        collector.collect(
            _task(tmp_path, access_mode=StyleAccessMode.AUTHENTICATED),
            credential=SecretValue(
                json.dumps({"schema_version": 1, "username": "operator", "password": "secret"})
            ),
            before_navigation=lambda _url: None,
        )


def test_production_remote_runtime_uses_protocol_connection_not_local_launch(tmp_path) -> None:
    runtime = _FakePlaywright()
    collector = PlaywrightStyleCollector(
        registry=load_style_adapter_registry(_registry_file(tmp_path)),
        chromium_executable="/fixture/chromium",
        browser_ws_endpoint="ws://style-browser-runtime:9222/",
        allowed_egress_hosts=("reviews.example", "login.example"),
        playwright_factory=lambda: runtime,
        clock=lambda: NOW,
    )

    collector.collect(
        _task(tmp_path, access_mode=StyleAccessMode.PUBLIC),
        credential=None,
        before_navigation=lambda _url: None,
    )

    assert runtime.chromium.connect_endpoint == "ws://style-browser-runtime:9222/"
    assert runtime.browser.launch_kwargs == {}
    assert runtime.browser.last_context is not None
    assert runtime.browser.last_context.web_socket_closed is True


def test_capture_exception_always_closes_context_and_removes_har(tmp_path) -> None:
    runtime = _FakePlaywright()
    runtime.browser.fail_screenshot = True
    collector = PlaywrightStyleCollector(
        registry=load_style_adapter_registry(_registry_file(tmp_path)),
        chromium_executable="/fixture/chromium",
        allowed_egress_hosts=("reviews.example", "login.example"),
        playwright_factory=lambda: runtime,
        clock=lambda: NOW,
    )
    task = _task(tmp_path, access_mode=StyleAccessMode.AUTHENTICATED)
    har_path = tmp_path / f"{task.collection_run_id}-{task.job_id}.har"

    with pytest.raises(RuntimeError, match="screenshot fixture"):
        collector.collect(
            task,
            credential=SecretValue(
                json.dumps({"schema_version": 1, "username": "operator", "password": "secret"})
            ),
            before_navigation=lambda _url: None,
        )

    assert runtime.browser.last_context is not None
    assert runtime.browser.last_context.closed is True
    assert not har_path.exists()


def test_derived_redaction_rejects_mixed_email_and_unredacted_secret_marker(tmp_path) -> None:
    task = _task(tmp_path, access_mode=StyleAccessMode.PUBLIC)
    capture = StylePageCapture(
        final_url=task.source_url,
        navigation_chain=(task.source_url,),
        raw_bundle=bytearray(b"temporary"),
        raw_media_type="application/zip",
        captured_at=NOW,
        capture_release="fixture-v1",
    )
    extracted = ExtractedStyleText(
        payload=bytearray(b"email me@example.test password=still-secret"),
        record_count=1,
        parser_release="fixture-v1",
    )

    inspected = ConservativeStyleArtifactInspector().inspect_derived(task, capture, extracted)
    decision = govern_raw_artifact(inspected.inspection)

    assert [item.value for item in inspected.inspection.unresolved_findings] == ["password"]
    assert inspected.inspection.redaction_verified is False
    assert decision.persistence_allowed is False


def test_raw_detector_accepts_empty_password_control_but_rejects_secret_values(tmp_path) -> None:
    task = _task(tmp_path, access_mode=StyleAccessMode.AUTHENTICATED)
    empty_control = _capture_with_dom(task, b"<input type='password'>Password policy")
    secret_value = _capture_with_dom(
        task,
        b"<div>password=hunter2 session_token=secret-session-value</div>",
    )
    inspector = ConservativeStyleArtifactInspector()

    accepted = inspector.inspect_raw(task, empty_control)
    rejected = inspector.inspect_raw(task, secret_value)

    assert [item.value for item in accepted.inspection.detected_findings] == [
        "restricted_content"
    ]
    assert govern_raw_artifact(accepted.inspection).persistence_allowed is True
    assert {item.value for item in rejected.inspection.unresolved_findings} == {
        "password",
        "session_token",
    }
    assert govern_raw_artifact(rejected.inspection).persistence_allowed is False


def _registry_file(tmp_path: Path) -> Path:
    adapters = []
    for channel in sorted(STANDARD_STYLE_CHANNELS):
        adapters.append(
            {
                "channel": channel,
                "adapter_release": "style-reddit-v1" if channel == "reddit" else f"style-{channel}-v1",
                "content_selectors": ["article.review"],
                "allowed_resource_hosts": ["login.example", "reviews.example"],
                "admission_state": (
                    "live_canary_approved" if channel == "reddit" else "reviewed_fixture"
                ),
                "navigation_timeout_ms": 5_000,
                "settle_timeout_ms": 0,
                "login_flow": (
                    {
                        "login_url": "https://login.example/sign-in",
                        "username_selector": "#username",
                        "password_selector": "#password",
                        "submit_selector": "button[type=submit]",
                        "success_selector": "[data-login-complete]",
                    }
                    if channel == "reddit"
                    else None
                ),
            }
        )
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {"schema_version": 1, "release_id": "style-adapters-v1", "adapters": adapters}
        ),
        encoding="utf-8",
    )
    return path


def _capture_with_dom(task: StyleCollectionTask, dom: bytes) -> StylePageCapture:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("page.html", dom)
        bundle.writestr("viewport.png", b"png")
        bundle.writestr("network.har.json", b"{}")
        bundle.writestr("style-records.json", b'["review"]')
    return StylePageCapture(
        final_url=task.source_url,
        navigation_chain=(task.source_url,),
        raw_bundle=bytearray(output.getvalue()),
        raw_media_type="application/zip",
        captured_at=NOW,
        capture_release="fixture-v1",
    )


def _task(tmp_path: Path, *, access_mode: StyleAccessMode) -> StyleCollectionTask:
    authorization_id = uuid4()
    binding = AuthorizationBinding(
        authorization_id=authorization_id,
        project_id=PROJECT_ID,
        channel="reddit",
        adapter_release="style-reddit-v1",
        version_number=2,
        authorization_hash=_hash("authorization"),
        purpose="style_collection",
        expires_at=NOW + timedelta(days=1),
    )
    handle = (
        SecretVersionHandle(
            reference_id=uuid4(),
            project_id=PROJECT_ID,
            purpose="style_collection_login.reddit",
            version=1,
        )
        if access_mode is StyleAccessMode.AUTHENTICATED
        else None
    )
    return StyleCollectionTask(
        project_id=PROJECT_ID,
        job_id=uuid4(),
        collection_run_id=uuid4(),
        style_source_revision_id=uuid4(),
        source_revision_number=1,
        channel="reddit",
        locale="en-AU",
        access_mode=access_mode,
        source_url="https://reviews.example/start",
        source_locator_hash=_hash("source"),
        adapter_release="style-reddit-v1",
        authorization=binding,
        login_secret=handle,
        allowed_redirect_hosts=("login.example", "reviews.example"),
        robots_user_agent="GeoStyleResearchBot/1.0",
        raw_artifact_id=uuid4(),
        derived_artifact_id=uuid4(),
        tmpfs=TmpfsCapturePolicy(mount_path=str(tmp_path), maximum_bytes=2_000_000),
    )


class _FakeResponse:
    status = 200


class _FakeRequest:
    def __init__(self, url: str, *, navigation: bool = True, resource_type: str = "document") -> None:
        self.url = url
        self.resource_type = resource_type
        self.navigation = navigation

    def is_navigation_request(self) -> bool:
        return self.navigation


class _FakeRoute:
    def __init__(self, url: str, *, navigation: bool = True, resource_type: str = "document") -> None:
        self.request = _FakeRequest(url, navigation=navigation, resource_type=resource_type)
        self.aborted = False

    def continue_(self) -> None:
        return None

    def abort(self, reason: str) -> None:
        del reason
        self.aborted = True


class _FakeLocator:
    def __init__(self, selector: str) -> None:
        self.selector = selector

    def fill(self, value: str) -> None:
        del value

    def click(self) -> None:
        return None

    def wait_for(self, *, state: str) -> None:
        assert state == "visible"

    def inner_text(self, *, timeout: int) -> str:
        del timeout
        return "normal page"

    def all_inner_texts(self) -> list[str]:
        return [" Useful Australian review "] if self.selector == "article.review" else []

    def evaluate_all(self, script: str) -> None:
        assert "element.value = ''" in script


class _FakePage:
    def __init__(self, context: "_FakeContext") -> None:
        self.context = context
        self.url = "about:blank"

    def set_default_timeout(self, value: int) -> None:
        del value

    def set_default_navigation_timeout(self, value: int) -> None:
        del value

    def goto(self, url: str, *, wait_until: str) -> _FakeResponse:
        assert wait_until == "domcontentloaded"
        destinations = [url]
        if url == "https://reviews.example/start":
            destinations.append("https://reviews.example/final")
        for destination in destinations:
            route = _FakeRoute(destination)
            self.context.route_handler(route)
            if route.aborted:
                raise RuntimeError("fixture route aborted")
            self.url = destination
        if self.context.subresource_url is not None:
            self.context.route_handler(
                _FakeRoute(
                    self.context.subresource_url,
                    navigation=False,
                    resource_type="script",
                )
            )
        return _FakeResponse()

    def wait_for_timeout(self, value: int) -> None:
        del value

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(selector)

    def screenshot(self, **values) -> bytes:
        del values
        if self.context.fail_screenshot:
            raise RuntimeError("screenshot fixture failed")
        return b"fixture-png"

    def content(self) -> str:
        return (
            "<html><input type='password'>"
            "<article class='review'>Useful Australian review</article></html>"
        )


class _FakeContext:
    def __init__(
        self,
        values: dict[str, object],
        *,
        subresource_url: str | None,
        fail_screenshot: bool,
    ) -> None:
        self.values = values
        self.har_path = Path(str(values["record_har_path"]))
        self.route_handler = lambda route: None
        self.page = _FakePage(self)
        self.subresource_url = subresource_url
        self.fail_screenshot = fail_screenshot
        self.closed = False
        self.web_socket_closed = False

    def route(self, pattern: str, handler) -> None:
        assert pattern == "**/*"
        self.route_handler = handler

    def route_web_socket(self, pattern: str, handler) -> None:
        assert pattern == "**/*"
        context = self

        class Socket:
            def close(self) -> None:
                context.web_socket_closed = True

        handler(Socket())

    def new_page(self) -> _FakePage:
        return self.page

    def close(self) -> None:
        self.closed = True
        self.har_path.write_text(
            json.dumps(
                {
                    "log": {
                        "entries": [
                            {
                                "request": {
                                    "url": "https://reviews.example/final?token=secret",
                                    "headers": [
                                        {"name": "Authorization", "value": "Bearer credential"},
                                        {"name": "Cookie", "value": "sid=credential"},
                                    ],
                                    "postData": {"text": "S3cret!"},
                                }
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )


class _FakeBrowser:
    def __init__(self) -> None:
        self.launch_kwargs: dict[str, object] = {}
        self.subresource_url: str | None = None
        self.fail_screenshot = False
        self.last_context: _FakeContext | None = None

    def new_context(self, **values) -> _FakeContext:
        self.last_context = _FakeContext(
            values,
            subresource_url=self.subresource_url,
            fail_screenshot=self.fail_screenshot,
        )
        return self.last_context

    def close(self) -> None:
        return None


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.connect_endpoint: str | None = None

    def launch(self, **values) -> _FakeBrowser:
        self.browser.launch_kwargs = values
        return self.browser

    def connect(self, endpoint: str) -> _FakeBrowser:
        assert endpoint == "ws://style-browser-runtime:9222/"
        self.connect_endpoint = endpoint
        return self.browser


class _FakePlaywright(AbstractContextManager):
    def __init__(self) -> None:
        self.browser = _FakeBrowser()
        self.chromium = _FakeChromium(self.browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
