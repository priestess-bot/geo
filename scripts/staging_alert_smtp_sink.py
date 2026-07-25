"""Private SMTP sink used only by the staging Compose override.

It accepts the narrow SMTP conversation emitted by LocalSmtpTransport and
discards message bytes.  This keeps staging notification checks local rather
than silently sending test alerts to an external SMTP provider.
"""

from __future__ import annotations

import asyncio
import os


_MAX_LINE = 16_384


async def _reply(writer: asyncio.StreamWriter, code: int, message: str) -> None:
    writer.write(f"{code} {message}\r\n".encode("ascii"))
    await writer.drain()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    in_data = False
    try:
        await _reply(writer, 220, "geo-staging-alert-sink")
        while True:
            line = await reader.readline()
            if not line or len(line) > _MAX_LINE:
                return
            if in_data:
                if line == b".\r\n":
                    in_data = False
                    await _reply(writer, 250, "accepted")
                continue
            verb = line.decode("ascii", "replace").strip().split(" ", 1)[0].upper()
            if verb in {"EHLO", "HELO", "MAIL", "RCPT", "RSET", "NOOP"}:
                await _reply(writer, 250, "ok")
            elif verb == "DATA":
                in_data = True
                await _reply(writer, 354, "end with <CRLF>.<CRLF>")
            elif verb == "QUIT":
                await _reply(writer, 221, "bye")
                return
            else:
                await _reply(writer, 502, "unsupported")
    finally:
        writer.close()
        await writer.wait_closed()


async def _serve() -> None:
    port = int(os.getenv("GEO_STAGING_ALERT_SMTP_SINK_PORT", "8025"))
    server = await asyncio.start_server(_handle, host="0.0.0.0", port=port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_serve())
