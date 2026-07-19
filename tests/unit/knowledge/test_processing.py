from io import BytesIO
import hashlib
import socket
from zipfile import ZipFile

import pytest

from geo_core.knowledge.domain import KnowledgeProcessingError, ProcessingInput
from geo_core.knowledge.processing import _parse, _require_public_url, process_source
from geo_core.knowledge.processing import extract_fact_candidates
from geo_core.knowledge.domain import ChunkDraft


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
