"""Private HTTP sink used only by the staging Compose override."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import ssl


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 1_048_576:
            self.send_error(413)
            return
        self.rfile.read(length)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


if __name__ == "__main__":
    port = int(os.getenv("GEO_STAGING_ALERT_WEBHOOK_SINK_PORT", "8080"))
    certificate = Path(os.environ["GEO_STAGING_ALERT_WEBHOOK_TLS_CERT_FILE"])
    private_key = Path(os.environ["GEO_STAGING_ALERT_WEBHOOK_TLS_KEY_FILE"])
    if certificate.is_symlink() or private_key.is_symlink():
        raise RuntimeError("staging webhook TLS files must not be symlinks")
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certificate, keyfile=private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
