from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
import os
from pathlib import Path
import re
import smtplib
import ssl


_ADDRESS = re.compile(r"^[^\s@<>]+@[^\s@<>]+$")
_MAX_LINE = 16_384
_MAX_MESSAGE = 128 * 1024


@dataclass(frozen=True)
class RelayConfig:
    upstream_host: str
    upstream_port: int
    tls_mode: str
    username: str
    password: str
    allowed_sender: str
    allowed_recipients: frozenset[str]
    listen_port: int = 8025

    @classmethod
    def from_environment(cls) -> "RelayConfig":
        host = _required("GEO_ALERT_SMTP_UPSTREAM_HOST").lower()
        allowed_hosts = _csv(_required("GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS"))
        if host not in allowed_hosts:
            raise RuntimeError("SMTP upstream host is not exactly allowlisted")
        tls_mode = os.getenv("GEO_ALERT_SMTP_TLS_MODE", "starttls").strip().lower()
        if tls_mode not in {"starttls", "tls"}:
            raise RuntimeError("GEO_ALERT_SMTP_TLS_MODE must be starttls or tls")
        sender = _address(_required("GEO_ALERT_SMTP_SENDER"))
        recipients = frozenset(
            _address(value) for value in _csv(_required("GEO_ALERT_SMTP_RECIPIENTS"))
        )
        if not recipients:
            raise RuntimeError("SMTP relay recipients cannot be empty")
        return cls(
            upstream_host=host,
            upstream_port=_bounded_int(
                "GEO_ALERT_SMTP_UPSTREAM_PORT",
                587 if tls_mode == "starttls" else 465,
                1,
                65535,
            ),
            tls_mode=tls_mode,
            username=_secret("GEO_ALERT_SMTP_USERNAME"),
            password=_secret("GEO_ALERT_SMTP_PASSWORD"),
            allowed_sender=sender,
            allowed_recipients=recipients,
            listen_port=_bounded_int("GEO_ALERT_SMTP_RELAY_PORT", 8025, 1024, 65535),
        )


class RestrictedSmtpRelay:
    def __init__(self, config: RelayConfig) -> None:
        self._config = config

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sender: str | None = None
        recipients: list[str] = []
        try:
            await _reply(writer, 220, "geo-alert-smtp-relay")
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=30)
                if not line or len(line) > _MAX_LINE:
                    return
                command = line.decode("ascii", "replace").strip()
                verb, _, argument = command.partition(" ")
                verb = verb.upper()
                if verb in {"EHLO", "HELO"}:
                    sender, recipients = None, []
                    await _reply(writer, 250, "geo-alert-smtp-relay")
                elif verb == "NOOP":
                    await _reply(writer, 250, "ok")
                elif verb == "RSET":
                    sender, recipients = None, []
                    await _reply(writer, 250, "reset")
                elif verb == "QUIT":
                    await _reply(writer, 221, "bye")
                    return
                elif verb == "MAIL" and argument.upper().startswith("FROM:"):
                    candidate = _smtp_path(argument[5:])
                    if candidate != self._config.allowed_sender:
                        await _reply(writer, 550, "sender rejected")
                    else:
                        sender, recipients = candidate, []
                        await _reply(writer, 250, "sender accepted")
                elif verb == "RCPT" and argument.upper().startswith("TO:") and sender:
                    candidate = _smtp_path(argument[3:])
                    if candidate not in self._config.allowed_recipients:
                        await _reply(writer, 550, "recipient rejected")
                    else:
                        recipients.append(candidate)
                        await _reply(writer, 250, "recipient accepted")
                elif verb == "DATA" and sender and recipients:
                    await _reply(writer, 354, "end with <CRLF>.<CRLF>")
                    content = await _read_data(reader)
                    try:
                        message = _validated_message(
                            content,
                            sender=sender,
                            recipients=tuple(recipients),
                            config=self._config,
                        )
                        await asyncio.to_thread(self._forward, message)
                    except (ValueError, OSError, smtplib.SMTPException):
                        await _reply(writer, 451, "relay unavailable")
                    else:
                        await _reply(writer, 250, "queued")
                    sender, recipients = None, []
                else:
                    await _reply(writer, 503, "bad sequence")
        finally:
            writer.close()
            await writer.wait_closed()

    def _forward(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._config.tls_mode == "tls":
            with smtplib.SMTP_SSL(
                self._config.upstream_host,
                self._config.upstream_port,
                timeout=15,
                context=context,
            ) as client:
                client.login(self._config.username, self._config.password)
                client.send_message(message)
            return
        with smtplib.SMTP(
            self._config.upstream_host,
            self._config.upstream_port,
            timeout=15,
        ) as client:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
            client.login(self._config.username, self._config.password)
            client.send_message(message)


async def _main() -> None:
    config = RelayConfig.from_environment()
    relay = RestrictedSmtpRelay(config)
    server = await asyncio.start_server(relay.handle, host="0.0.0.0", port=config.listen_port)
    async with server:
        await server.serve_forever()


def _validated_message(
    content: bytes,
    *,
    sender: str,
    recipients: tuple[str, ...],
    config: RelayConfig,
) -> EmailMessage:
    parsed = BytesParser(policy=policy.SMTP).parsebytes(content)
    if not isinstance(parsed, EmailMessage):
        raise ValueError("SMTP payload is not an EmailMessage")
    header_sender = _address(str(parsed.get("From", "")))
    header_recipients = frozenset(
        _address(item.strip()) for item in str(parsed.get("To", "")).split(",") if item.strip()
    )
    if (
        sender != config.allowed_sender
        or header_sender != sender
        or frozenset(recipients) != header_recipients
        or not header_recipients.issubset(config.allowed_recipients)
        or parsed.get("Bcc") is not None
    ):
        raise ValueError("SMTP envelope differs from sanitized headers")
    return parsed


async def _read_data(reader: asyncio.StreamReader) -> bytes:
    values = bytearray()
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=30)
        if not line or len(line) > _MAX_LINE:
            raise ValueError("SMTP DATA line is invalid")
        if line == b".\r\n":
            return bytes(values)
        if line.startswith(b".."):
            line = line[1:]
        values.extend(line)
        if len(values) > _MAX_MESSAGE:
            raise ValueError("SMTP DATA exceeds the alert limit")


async def _reply(writer: asyncio.StreamWriter, status: int, message: str) -> None:
    writer.write(f"{status} {message}\r\n".encode("ascii"))
    await writer.drain()


def _smtp_path(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("<") and normalized.endswith(">"):
        normalized = normalized[1:-1]
    return _address(normalized)


def _address(value: str) -> str:
    normalized = value.strip().lower()
    if not _ADDRESS.fullmatch(normalized) or len(normalized) > 254:
        raise ValueError("email address is invalid")
    return normalized


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _secret(name: str) -> str:
    direct = os.getenv(name, "").strip()
    path = os.getenv(f"{name}_FILE", "").strip()
    if direct or not path:
        raise RuntimeError(f"{name}_FILE is required and direct secret values are forbidden")
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"{name}_FILE cannot be read") from error
    if not value:
        raise RuntimeError(f"{name}_FILE is empty")
    return value


def _csv(value: str) -> frozenset[str]:
    return frozenset(item.strip().lower() for item in value.split(",") if item.strip())


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} is outside its allowed range")
    return value


if __name__ == "__main__":
    asyncio.run(_main())
