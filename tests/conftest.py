"""Shared fixtures: a local API that accepts only a bearer key full of URL-reserved characters."""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

BEARER = "k3y+with/special=" + secrets.token_hex(8)  # URL-reserved chars on purpose


class _BearerAPI(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.headers.get("Authorization") != f"Bearer {BEARER}":
            return self._send(401, {"error": "unauthorized"})
        city = parse_qs(urlparse(self.path).query).get("city", ["?"])[0]
        self._send(200, {"city": city, "temp_c": 21})

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def bearer_api():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _BearerAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
