"""Run the local LORMesh web demo with Python's standard library only."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from .demo_system import DemoSystem


WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
SYSTEM = DemoSystem()


class LormeshHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(200, SYSTEM.state())
            return
        if path == "/" or path == "/index.html":
            self._send_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
            return
        if path in ("/app.js", "/styles.css"):
            content_type = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
            self._send_file(WEB_ROOT / path.lstrip("/"), content_type)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/message":
                result = SYSTEM.send_message(
                    self._string(body, "source", "A"),
                    self._string(body, "destination", "C"),
                    self._string(body, "text"),
                )
                self._send_json(200, result)
                return
            if path == "/api/sos":
                result = SYSTEM.send_sos(self._string(body, "source", "A"))
                self._send_json(200, result)
                return
            if path == "/api/node-status":
                result = SYSTEM.set_node_online(
                    self._string(body, "node_id"), self._boolean(body, "online")
                )
                self._send_json(200, result)
                return
            if path == "/api/connection-mode":
                result = SYSTEM.set_connection_mode(self._string(body, "mode"))
                self._send_json(200, result)
                return
            if path == "/api/gps/nmea":
                result = SYSTEM.set_gps_from_nmea(
                    self._string(body, "node_id"), self._string(body, "sentence")
                )
                self._send_json(200, result)
                return
            if path == "/api/reset":
                self._send_json(200, SYSTEM.reset())
                return
            self._send_json(404, {"error": "not found"})
        except (ValueError, TimeoutError) as error:
            self._send_json(400, {"error": str(error)})

    def _read_json(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise ValueError("multiple Content-Length headers are not allowed")
        length = int(lengths[0]) if lengths else 0
        if not 0 <= length <= 4096:
            raise ValueError("Content-Length must be between 0 and 4096 bytes")
        self.connection.settimeout(5)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("incomplete request body")
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        return body

    @staticmethod
    def _string(body: dict, key: str, default: str = "") -> str:
        value = body.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        return value

    @staticmethod
    def _boolean(body: dict, key: str) -> bool:
        value = body.get(key)
        if type(value) is not bool:
            raise ValueError(f"{key} must be a boolean")
        return value

    def _send_json(self, status: int, payload: dict) -> None:
        # Escaping also keeps error responses encodable for malformed Unicode
        # sent as JSON escapes (for example an unpaired surrogate in a node ID).
        encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send_json(404, {"error": "file not found"})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[LORMesh] {self.address_string()} - {format % args}")


def main() -> None:
    address = ("127.0.0.1", 8765)
    server = ThreadingHTTPServer(address, LormeshHandler)
    print(f"LORMesh demo running at http://{address[0]}:{address[1]}")
    print("Press Ctrl+C to stop. This is a local simulation, not a radio AP.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LORMesh demo.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
