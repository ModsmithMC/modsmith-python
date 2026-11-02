"""A real HTTP server on a real socket.

Replies are queued per path and the last one repeats, so a test can script
"fail twice, then succeed". Range requests and dropped connections are real.
"""

import json
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Reply:
    body: bytes = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    drop_after: int | None = None
    ranges: bool = True


@dataclass
class Recorded:
    method: str
    path: str
    query: str
    headers: dict[str, str]


class LocalServer:
    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], deque[Reply]] = {}
        self.requests: list[Recorded] = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                owner.handle(self, "GET")

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_port}"

    def url(self, path: str = "/") -> str:
        return self.base + path

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def add(self, path: str, *replies: Reply) -> str:
        self.routes[("GET", path)] = deque(replies)
        return self.url(path)

    def add_body(self, path: str, body: bytes) -> str:
        return self.add(path, Reply(body))

    def add_json(self, path: str, data: Any) -> str:
        return self.add(path, Reply(json.dumps(data).encode()))

    def hits(self, path: str) -> list[Recorded]:
        return [request for request in self.requests if request.path == path]

    def handle(self, handler: BaseHTTPRequestHandler, method: str) -> None:
        url = urlsplit(handler.path)
        with self._lock:
            self.requests.append(
                Recorded(method, url.path, url.query, dict(handler.headers))
            )
            queue = self.routes.get((method, url.path))
            if queue is None:
                reply = Reply(b"not found", 404)
            else:
                reply = queue.popleft() if len(queue) > 1 else queue[0]
        self._send(handler, reply)

    def _send(self, handler: BaseHTTPRequestHandler, reply: Reply) -> None:
        status, body = reply.status, reply.body
        headers = dict(reply.headers)
        match = re.fullmatch(r"bytes=(\d+)-", handler.headers.get("Range") or "")
        if_range = handler.headers.get("If-Range")
        fresh = if_range is None or if_range == headers.get("ETag")
        if match and fresh and reply.ranges and status == 200:
            offset = int(match[1])
            if offset >= len(body):
                status, body = 416, b""
            else:
                last = len(body) - 1
                headers["Content-Range"] = f"bytes {offset}-{last}/{len(body)}"
                status, body = 206, body[offset:]

        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            handler.send_header(name, value)
        handler.end_headers()
        if reply.drop_after is None:
            handler.wfile.write(body)
            return
        handler.wfile.write(body[: reply.drop_after])
        handler.wfile.flush()
        handler.close_connection = True
