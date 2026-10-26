"""Integration checks against a real HTTP server on an ephemeral loopback port."""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import unittest
from unittest.mock import patch

from lormesh.demo_system import DemoSystem
from lormesh import server as app


class QuietHandler(app.LormeshHandler):
    def log_message(self, *args):
        pass


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.system_patch = patch.object(app, "SYSTEM", DemoSystem())
        self.system_patch.start()
        self.addCleanup(self.system_patch.stop)

    def request(self, path, data=None, *, raw=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            method = "POST" if data is not None or raw is not None else "GET"
            body = raw if raw is not None else json.dumps(data) if data is not None else None
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            content = response.read()
            return response.status, dict(response.getheaders()), content
        finally:
            connection.close()

    def post(self, path, data):
        status, _, body = self.request(path, data)
        return status, json.loads(body)

    def test_all_assets_and_not_found(self):
        for path, content_type in (("/", "text/html"), ("/index.html", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn(content_type, headers["Content-Type"])
                self.assertGreater(len(body), 100)
        for path in ("/missing", "/../README.md", "/api/unknown"):
            self.assertEqual(self.request(path)[0], 404)

    def test_complete_api_workflow(self):
        self.assertEqual(self.post("/api/message", {"source": "A", "destination": "C", "text": "ช่วยด้วย"})[1]["path"], ["A", "B", "C"])
        self.assertEqual(self.post("/api/message", {"text": "Again"})[1]["routing_mode"], "cached_route")
        self.assertEqual(self.post("/api/node-status", {"node_id": "B", "online": False})[0], 200)
        self.assertEqual(self.post("/api/message", {"text": "Fallback"})[1]["path"], ["A", "D", "C"])
        self.assertEqual(self.post("/api/connection-mode", {"mode": "ble"})[1]["connection_mode"], "ble")
        self.assertEqual(self.post("/api/gps/nmea", {"node_id": "A", "sentence": "$GPRMC,123519,A,1345.3600,N,10030.0600,E"})[0], 200)
        self.assertEqual(set(self.post("/api/sos", {"source": "A"})[1]["recipients"]), {"C", "D"})
        state = self.post("/api/reset", {})[1]
        self.assertEqual(state["messages"], [])
        self.assertEqual(state["connection_mode"], "wifi")
        self.assertTrue(all(n["online"] for n in state["nodes"]))

    def test_invalid_json_shapes_return_400_and_server_survives(self):
        for raw in ("null", "[]", "123", '"text"', "{", b"\xff"):
            with self.subTest(raw=raw):
                self.assertEqual(self.request("/api/message", raw=raw)[0], 400)
        self.assertEqual(self.request("/api/state")[0], 200)

    def test_invalid_field_types_are_rejected_without_mutation(self):
        cases = [
            ("/api/node-status", {"node_id": "B", "online": "false"}),
            ("/api/node-status", {"node_id": "B", "online": 0}),
            ("/api/node-status", {"node_id": "B"}),
            ("/api/message", {"text": None}),
            ("/api/message", {"text": 123}),
            ("/api/message", {"source": [], "text": "Hi"}),
            ("/api/message", {"source": "\ud800", "text": "Hi"}),
            ("/api/message", {"text": "x" * 201}),
            ("/api/message", {"source": "A", "destination": "A", "text": "Hi"}),
            ("/api/sos", {"source": "unknown"}),
            ("/api/connection-mode", {"mode": "invalid"}),
            ("/api/gps/nmea", {"node_id": "A", "sentence": "$GPRMC,123519,A,inf,N,10030.0600,E"}),
            ("/api/gps/nmea", {"node_id": "A", "sentence": "$\ud800RMC,123519,A,1345.3600,N,10030.0600,E"}),
        ]
        for path, data in cases:
            with self.subTest(path=path, data=data):
                self.assertEqual(self.post(path, data)[0], 400)
        self.assertEqual(app.SYSTEM.state()["messages"], [])
        self.assertTrue(all(n["online"] for n in app.SYSTEM.state()["nodes"]))

    def test_invalid_content_lengths_are_rejected(self):
        for length in ("-1", "not-a-number", "4097"):
            with self.subTest(length=length):
                self.assertEqual(self.request("/api/message", raw=b"", headers={"Content-Length": length})[0], 400)

    def test_parallel_sends_have_unique_ids_and_complete_history(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda i: self.post("/api/message", {"text": f"Message {i}"}), range(24)))
        self.assertTrue(all(status == 200 and item["delivered"] for status, item in results))
        self.assertEqual(len({item["id"] for _, item in results}), 24)
        state = json.loads(self.request("/api/state")[2])
        self.assertEqual(len(state["messages"]), 24)


if __name__ == "__main__":
    unittest.main()
