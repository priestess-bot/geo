from io import BytesIO
import hashlib
import socket
from zipfile import ZipFile

import httpx
import pytest

from geo_core.knowledge.domain import ChunkDraft, KnowledgeProcessingError, ProcessingInput
from geo_core.knowledge.processing import (
    _PinnedIPTransport,
    _fetch_public_url,
    _parse,
    _require_public_url,
    extract_fact_candidates,
    process_source,
)


def _input(content: bytes, *, media_type: str, filename: str) -> ProcessingInput:
    from uuid import uuid4

    return ProcessingInput(
        source_id=uuid4(),
        pipeline_run_id=uuid4(),
        project_id=uuid4(),
        source_kind="file",
        title=filename,
        source_url=None,
        filename=filename,
        media_type=media_type,
        raw_content=content,
    )


def test_html_processing_removes_hidden_content_and_builds_lineage() -> None:
    result = process_source(
        _input(
            b"<html><script>secret</script><h1>ADVINSYS V600</h1><p>The product supports "
            b"lawns up to 600 square metres according to the official product page.</p></html>",
            media_type="text/html",
            filename="product.html",
        )
    )
    assert "secret" not in result.cleaned_text
    assert "ADVINSYS V600" in result.cleaned_text
    assert result.chunks
    assert result.facts
    assert len(result.cleaned_text_hash) == 64


def test_fact_hash_preserves_exact_statement_while_dedup_is_case_insensitive() -> None:
    statement = (
        "The official ADVINSYS page identifies TerraMow V600 as a Triple-Cam AI "
        "Vision Robot Mower."
    )
    chunks = (
        ChunkDraft(statement, hashlib.sha256(statement.encode()).hexdigest(), len(statement), ()),
        ChunkDraft(
            statement.lower(),
            hashlib.sha256(statement.lower().encode()).hexdigest(),
            len(statement),
            (),
        ),
    )

    facts = extract_fact_candidates(chunks)

    assert len(facts) == 1
    assert facts[0].statement == statement
    assert facts[0].statement_hash == hashlib.sha256(statement.encode()).hexdigest()


def test_docx_parser_extracts_paragraph_text_without_optional_office_runtime() -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body><w:p><w:r><w:t>Official product documentation for Australia.</w:t></w:r></w:p>
            <w:p><w:r><w:t>Warranty claims require human evidence review.</w:t></w:r></w:p></w:body>
            </w:document>""",
        )
    assert (
        _parse(
            buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="facts.docx",
        )
        == "Official product documentation for Australia.\nWarranty claims require human evidence review."
    )


def test_public_url_validation_uses_protocol_default_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def resolve(host: str, port: int, *, type: int):
        del host, type
        calls.append(port)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    _require_public_url("http://example.com/path")
    _require_public_url("https://example.com/path")
    assert calls == [80, 443]


def test_public_url_validation_rejects_private_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )
    with pytest.raises(KnowledgeProcessingError, match="non-public"):
        _require_public_url("http://internal.example")


def test_public_url_validation_rejects_embedded_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = False

    def resolve(*args: object, **kwargs: object) -> list[object]:
        nonlocal resolved
        del args, kwargs
        resolved = True
        return []

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    with pytest.raises(KnowledgeProcessingError, match="public HTTP or HTTPS"):
        _require_public_url("https://user:secret@source.example/document")

    assert resolved is False


@pytest.mark.parametrize("port", (0, -1, 65536, 65616))
def test_public_url_validation_rejects_out_of_range_ports(
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    resolved = False

    def resolve(*args: object, **kwargs: object) -> list[object]:
        nonlocal resolved
        del args, kwargs
        resolved = True
        return []

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    with pytest.raises(KnowledgeProcessingError, match="port must be between"):
        _require_public_url(f"http://source.example:{port}/document")

    assert resolved is False


@pytest.mark.parametrize(
    "address",
    (
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "64:ff9b:1::7f00:1",
        "::7f00:1",
    ),
)
def test_public_url_validation_rejects_ipv4_transition_to_non_public_address(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 443, 0, 0))
        ],
    )

    with pytest.raises(KnowledgeProcessingError, match="non-public"):
        _require_public_url("https://transition.example/document")


def test_public_url_validation_rejects_mixed_public_and_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ],
    )

    with pytest.raises(KnowledgeProcessingError, match="non-public"):
        _require_public_url("https://mixed.example/document")


@pytest.mark.parametrize(
    ("address", "expected_url"),
    [
        ("93.184.216.34", "https://93.184.216.34:8443/document"),
        (
            "2606:2800:220:1:248:1893:25c8:1946",
            "https://[2606:2800:220:1:248:1893:25c8:1946]:8443/document",
        ),
    ],
)
def test_pinned_transport_preserves_host_and_tls_identity(
    address: str,
    expected_url: str,
) -> None:
    captured: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=b"fixture")

    transport = _PinnedIPTransport(
        (address,),
        "source.example",
        transport_factory=lambda: httpx.MockTransport(handle),
    )
    with httpx.Client(transport=transport, trust_env=False) as client:
        response = client.get("https://source.example:8443/document")

    assert response.content == b"fixture"
    assert len(captured) == 1
    assert str(captured[0].url) == expected_url
    assert captured[0].headers["host"] == "source.example:8443"
    assert captured[0].extensions["sni_hostname"] == "source.example"


def test_pinned_transport_closes_failed_protocol_transport() -> None:
    class FailingTransport(httpx.BaseTransport):
        def __init__(self) -> None:
            self.closed = False

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            del request
            raise httpx.ProtocolError("invalid upstream response")

        def close(self) -> None:
            self.closed = True

    failing = FailingTransport()
    transport = _PinnedIPTransport(
        ("93.184.216.34",),
        "source.example",
        transport_factory=lambda: failing,
    )

    with pytest.raises(httpx.ProtocolError, match="invalid upstream"):
        transport.handle_request(httpx.Request("GET", "https://source.example/document"))

    assert failing.closed is True


def test_fetch_does_not_resolve_hostname_again_after_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = 0
    captured: list[httpx.Request] = []

    def resolve(host: str, port: int, *, type: int):
        nonlocal resolutions
        del port, type
        assert host == "source.example"
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"Pinned public source fixture.",
        )

    def transport(*, trust_env: bool) -> httpx.BaseTransport:
        assert trust_env is False
        return httpx.MockTransport(handle)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpx, "HTTPTransport", transport)

    content, final_url, media_type = _fetch_public_url("http://source.example/document")

    assert content == b"Pinned public source fixture."
    assert final_url == "http://source.example/document"
    assert media_type == "text/plain"
    assert resolutions == 1
    assert captured[0].url.host == "93.184.216.34"
    assert captured[0].headers["host"] == "source.example"


def test_fetch_revalidates_and_repins_every_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[tuple[str, int]] = []
    captured: list[httpx.Request] = []
    addresses = {
        "first.example": (socket.AF_INET, "93.184.216.34"),
        "second.example": (socket.AF_INET6, "2606:2800:220:1:248:1893:25c8:1946"),
    }

    def resolve(host: str, port: int, *, type: int):
        del type
        lookups.append((host, port))
        family, address = addresses[host]
        socket_address = (address, port) if family == socket.AF_INET else (address, port, 0, 0)
        return [(family, socket.SOCK_STREAM, 6, "", socket_address)]

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.headers["host"] == "first.example":
            return httpx.Response(
                302,
                headers={"location": "https://second.example/final"},
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<p>Redirected public source fixture.</p>",
        )

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda *, trust_env: httpx.MockTransport(handle),
    )

    content, final_url, media_type = _fetch_public_url("http://first.example/start")

    assert content == b"<p>Redirected public source fixture.</p>"
    assert final_url == "https://second.example/final"
    assert media_type == "text/html"
    assert lookups == [("first.example", 80), ("second.example", 443)]
    assert [request.url.host for request in captured] == [
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    ]


def test_fetch_blocks_redirect_when_rebinding_changes_host_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolutions = 0
    requests = 0

    def resolve(host: str, port: int, *, type: int):
        nonlocal resolutions
        del host, type
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        del request
        requests += 1
        return httpx.Response(302, headers={"location": "/after-redirect"})

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda *, trust_env: httpx.MockTransport(handle),
    )

    with pytest.raises(KnowledgeProcessingError, match="non-public"):
        _fetch_public_url("http://rebind.example/start")

    assert resolutions == 2
    assert requests == 1
