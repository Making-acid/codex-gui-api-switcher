"""connectivity 单元测试：本地模拟 responses / models 端点。"""
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.connectivity import smoke_test, probe_models, test_connection


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _handle(self, kind):
        if self.path.startswith("/v1/models"):
            body = json.dumps({"data": [{"id": "m1"}, {"id": "m2"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/v1/responses"):
            if self.headers.get("Authorization") == "Bearer good-key":
                body = json.dumps({"id": "resp_1", "output": []}).encode()
                self.send_response(200)
            else:
                body = json.dumps({"error": {"message": "invalid key"}}).encode()
                self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        self._handle("get")

    def do_POST(self):
        self._handle("post")


class ConnectivityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_smoke_ok(self):
        r = smoke_test(self.base, "good-key", "m1")
        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)

    def test_smoke_bad_key(self):
        r = smoke_test(self.base, "bad-key", "m1")
        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 401)

    def test_probe_models(self):
        r = probe_models(self.base, "good-key")
        self.assertTrue(r["ok"])
        self.assertEqual(r["models"], ["m1", "m2"])

    def test_combined_passed(self):
        r = test_connection(self.base, "good-key", "m1")
        self.assertTrue(r["passed"])

    def test_combined_failed(self):
        r = test_connection(self.base, "bad-key", "m1")
        self.assertFalse(r["passed"])

    def test_connection_error(self):
        r = smoke_test("http://127.0.0.1:1/v1", "k", "m")
        self.assertFalse(r["ok"])
        self.assertIn("网络连接失败", r["error"])


if __name__ == "__main__":
    unittest.main()
