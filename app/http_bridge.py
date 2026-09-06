from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import threading
import urllib.parse
import urllib.request
from typing import Any


class BackendHttpBridge:
    """Localhost bridge between the HTML UI and the Python backend.

    This deliberately does not use pywebview's javascript API injection.  The
    interface is served by the same local server and talks to Python through a
    normal HTTP POST to /api, which is much less sensitive to pywebview/WebView2
    version differences.
    """

    def __init__(self, backend: Any, interface_file: str | Path) -> None:
        self.backend = backend
        self.interface_file = Path(interface_file)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Servidor local do DocFlow ainda nao foi iniciado.")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url

        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args) -> None:
                # A GUI nao deve escrever em console nem gerar ruido de servidor.
                return

            def _send(self, status: int, content_type: str, data: bytes) -> None:
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self) -> None:  # noqa: N802
                parsed_path = urllib.parse.urlparse(self.path).path
                if parsed_path in {"/", "/index.html"}:
                    try:
                        data = bridge.interface_file.read_bytes()
                        self._send(200, "text/html; charset=utf-8", data)
                    except Exception as exc:
                        self._send(500, "text/plain; charset=utf-8", str(exc).encode("utf-8", errors="replace"))
                    return

                if parsed_path == "/health":
                    self._send(200, "application/json; charset=utf-8", b'{"ok":true}')
                    return

                asset_name = urllib.parse.unquote(parsed_path.lstrip("/"))
                asset_path = (bridge.interface_file.parent / asset_name).resolve()
                asset_root = bridge.interface_file.parent.resolve()
                if asset_path.is_file() and asset_root in asset_path.parents:
                    content_type = mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream"
                    self._send(200, content_type, asset_path.read_bytes())
                    return

                self._send(404, "text/plain; charset=utf-8", b"Not found")

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api":
                    self._send(404, "application/json; charset=utf-8", b'{"type":"backendError","message":"Endpoint invalido."}')
                    return

                try:
                    raw_length = self.headers.get("Content-Length", "0")
                    length = int(raw_length or 0)
                    if length <= 0 or length > 2_000_000:
                        raise ValueError("Mensagem vazia ou grande demais.")
                    raw = self.rfile.read(length)
                    request = json.loads(raw.decode("utf-8"))
                    if not isinstance(request, dict):
                        raise ValueError("Mensagem invalida.")
                    response = bridge.backend.post_message(request)
                    encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
                    self._send(200, "application/json; charset=utf-8", encoded)
                except Exception as exc:
                    encoded = json.dumps(
                        {"type": "backendError", "message": str(exc)},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    self._send(500, "application/json; charset=utf-8", encoded)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="DocFlowLocalBridge",
            daemon=True,
        )
        self._thread.start()
        return self.url

    def health_check(self) -> None:
        """Fail startup early if the local bridge cannot answer."""
        request = urllib.request.Request(self.url + "health", method="GET")
        with urllib.request.urlopen(request, timeout=3.0) as response:
            if response.status != 200:
                raise RuntimeError("Servidor local do DocFlow nao respondeu corretamente.")

    def api_self_test(self) -> None:
        """Verify the exact POST route used by the UI before showing the window."""
        payload = json.dumps({"command": "ready"}).encode("utf-8")
        request = urllib.request.Request(
            self.url + "api",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5.0) as response:
            data = json.loads(response.read().decode("utf-8"))
        if response.status != 200 or data.get("type") != "ready":
            raise RuntimeError("A comunicacao interna do DocFlow falhou no autoteste de inicializacao.")

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is None:
            return
        try:
            server.shutdown()
        finally:
            server.server_close()
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
