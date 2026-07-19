"""Deterministic retrieval, parsing, cleaning and chunking for knowledge sources."""

from __future__ import annotations

from html.parser import HTMLParser
import hashlib
from io import BytesIO
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

import httpx
from pypdf import PdfReader

from geo_core.knowledge.domain import (
    ChunkDraft,
    FactDraft,
    KnowledgeProcessingError,
    ProcessingInput,
    ProcessingResult,
    QualityFindingDraft,
)


MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 4
PARSER_VERSION = "geo-knowledge-parser-v1"
_SPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_depth += 1
        elif normalized in {
            "p",
            "div",
            "section",
            "article",
            "li",
            "br",
            "h1",
            "h2",
            "h3",
            "h4",
            "tr",
        }:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif normalized in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data)


def process_source(value: ProcessingInput) -> ProcessingResult:
    content, resolved_url, media_type = _source_bytes(value)
    raw_text = _parse(content, media_type=media_type, filename=value.filename)
    cleaned_text = clean_text(raw_text)
    if len(cleaned_text) < 40:
        raise KnowledgeProcessingError("source did not contain enough usable text")
    chunks = chunk_text(cleaned_text)
    facts = extract_fact_candidates(chunks)
    findings = quality_findings(cleaned_text, chunks, facts)
    return ProcessingResult(
        raw_content=content,
        resolved_url=resolved_url,
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        raw_text_hash=_sha(raw_text),
        cleaned_text_hash=_sha(cleaned_text),
        parser_version=PARSER_VERSION,
        chunks=chunks,
        facts=facts,
        findings=findings,
    )


def clean_text(raw_text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in raw_text.replace("\r", "\n").split("\n"):
        line = _SPACE.sub(" ", raw_line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def chunk_text(text: str, *, target_chars: int = 1200) -> tuple[ChunkDraft, ...]:
    paragraphs = [item.strip() for item in text.split("\n") if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        units = _split_long(paragraph, target_chars)
        for unit in units:
            candidate = f"{current}\n{unit}".strip() if current else unit
            if current and len(candidate) > target_chars:
                chunks.append(current)
                current = unit
            else:
                current = candidate
    if current:
        chunks.append(current)
    if not chunks:
        raise KnowledgeProcessingError("cleaning produced no chunks")
    result: list[ChunkDraft] = []
    seen: set[str] = set()
    for chunk in chunks:
        digest = _sha(chunk)
        flags: list[str] = []
        if len(chunk) < 120:
            flags.append("short_chunk")
        if digest in seen:
            flags.append("duplicate_chunk")
        seen.add(digest)
        result.append(ChunkDraft(chunk, digest, len(chunk), tuple(flags)))
    return tuple(result)


def extract_fact_candidates(chunks: tuple[ChunkDraft, ...]) -> tuple[FactDraft, ...]:
    result: list[FactDraft] = []
    seen_normalized: set[str] = set()
    for chunk_index, chunk in enumerate(chunks):
        for sentence in _SENTENCE.split(chunk.text.replace("\n", " ")):
            statement = sentence.strip()
            if not 45 <= len(statement) <= 500 or not re.search(r"[A-Za-z]", statement):
                continue
            normalized_hash = _sha(statement.casefold())
            if normalized_hash in seen_normalized:
                continue
            seen_normalized.add(normalized_hash)
            result.append(FactDraft(chunk_index, statement, _sha(statement)))
            if len(result) >= 100:
                return tuple(result)
    return tuple(result)


def quality_findings(
    cleaned_text: str,
    chunks: tuple[ChunkDraft, ...],
    facts: tuple[FactDraft, ...],
) -> tuple[QualityFindingDraft, ...]:
    findings: list[QualityFindingDraft] = []
    if len(cleaned_text) < 300:
        findings.append(
            QualityFindingDraft(
                None,
                "low_text_volume",
                "warning",
                "The source contains less than 300 characters of cleaned text.",
                {"char_count": len(cleaned_text)},
            )
        )
    if not facts:
        findings.append(
            QualityFindingDraft(
                None,
                "no_fact_candidates",
                "warning",
                "No reviewable factual sentences were extracted.",
                {},
            )
        )
    for index, chunk in enumerate(chunks):
        for flag in chunk.quality_flags:
            findings.append(
                QualityFindingDraft(
                    index,
                    flag,
                    "warning",
                    "Chunk requires review before downstream evidence use.",
                    {"char_count": chunk.char_count},
                )
            )
    return tuple(findings)


def _source_bytes(value: ProcessingInput) -> tuple[bytes, str | None, str]:
    if value.source_kind == "url":
        if not value.source_url:
            raise KnowledgeProcessingError("URL source is missing source_url")
        return _fetch_public_url(value.source_url)
    if value.raw_content is None:
        raise KnowledgeProcessingError("uploaded source content is missing")
    if len(value.raw_content) > MAX_SOURCE_BYTES:
        raise KnowledgeProcessingError("source exceeds the 5 MB processing limit")
    return value.raw_content, value.source_url, value.media_type


def _fetch_public_url(url: str) -> tuple[bytes, str, str]:
    current = url.strip()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            trust_env=False,
            headers={"User-Agent": "GEO-Knowledge-Ingest/1.0"},
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                _require_public_url(current)
                with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise KnowledgeProcessingError("source redirect has no location")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    for part in response.iter_bytes():
                        size += len(part)
                        if size > MAX_SOURCE_BYTES:
                            raise KnowledgeProcessingError("remote source exceeds the 5 MB limit")
                        chunks.append(part)
                    media_type = response.headers.get("content-type", "text/html").split(";", 1)[0]
                    return b"".join(chunks), str(response.url), media_type
    except KnowledgeProcessingError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise KnowledgeProcessingError(
            "remote source could not be reached", retryable=True
        ) from exc
    except httpx.HTTPStatusError as exc:
        retryable = exc.response.status_code >= 500 or exc.response.status_code == 429
        raise KnowledgeProcessingError(
            f"remote source returned HTTP {exc.response.status_code}", retryable=retryable
        ) from exc
    raise KnowledgeProcessingError("remote source exceeded the redirect limit")


def _require_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise KnowledgeProcessingError("source URL must be public HTTP or HTTPS")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise KnowledgeProcessingError(
            "source hostname could not be resolved", retryable=True
        ) from exc
    if not addresses:
        raise KnowledgeProcessingError("source hostname resolved to no addresses")
    for address in addresses:
        value = ipaddress.ip_address(address)
        if not value.is_global:
            raise KnowledgeProcessingError("source URL resolves to a non-public address")


def _parse(content: bytes, *, media_type: str, filename: str | None) -> str:
    normalized = media_type.lower()
    suffix = (filename or "").lower().rsplit(".", 1)[-1]
    if normalized in {"text/html", "application/xhtml+xml"} or suffix in {"html", "htm"}:
        parser = _VisibleTextParser()
        parser.feed(_decode(content))
        return "".join(parser.parts)
    if normalized == "application/json" or suffix == "json":
        try:
            payload = json.loads(_decode(content))
        except json.JSONDecodeError as exc:
            raise KnowledgeProcessingError("JSON source is invalid") from exc
        return "\n".join(_json_strings(payload))
    if normalized == "application/pdf" or suffix == "pdf":
        try:
            pages = PdfReader(BytesIO(content)).pages
            return "\n\n".join((page.extract_text() or "").strip() for page in pages)
        except Exception as exc:
            raise KnowledgeProcessingError("PDF source could not be parsed") from exc
    if (
        normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or suffix == "docx"
    ):
        return _parse_docx(content)
    if normalized.startswith("text/") or suffix in {"txt", "md", "csv", "tsv"}:
        return _decode(content)
    raise KnowledgeProcessingError(f"unsupported source media type: {media_type}")


def _parse_docx(content: bytes) -> str:
    try:
        with ZipFile(BytesIO(content)) as archive:
            document = ElementTree.fromstring(archive.read("word/document.xml"))
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise KnowledgeProcessingError("DOCX source could not be parsed") from exc
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in document.iter(f"{namespace}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _decode(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KnowledgeProcessingError("source text encoding is unsupported")


def _json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _json_strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _json_strings(child)]
    return []


def _split_long(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = _SENTENCE.split(text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if current:
                result.append(current)
                current = ""
            result.extend(
                sentence[index : index + limit] for index in range(0, len(sentence), limit)
            )
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > limit:
            result.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
