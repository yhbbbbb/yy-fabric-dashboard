import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from backend import admin_auth, server


class RoutePermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        admin_auth.ADMIN_DB_PATH = Path(cls.temp_dir.name) / "admin.sqlite"
        os.environ["YY_ADMIN_PASSWORD"] = "TestAdmin@123"
        admin_auth.init_admin_db()
        role = admin_auth.create_role("只看总览", "overview_reader", "", ["overview"])
        admin_auth.create_user("overview-user", "Overview@123", [role["id"]])
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.temp_dir.cleanup()

    def request(self, method, path, body=None, cookie=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        content = response.read()
        connection.close()
        return response, json.loads(content) if content else None

    def login(self):
        response, _ = self.request(
            "POST",
            "/api/auth/login",
            {"username": "overview-user", "password": "Overview@123"},
        )
        return response.getheader("Set-Cookie").split(";", 1)[0]

    def test_overview_user_can_use_overview_but_not_analytics(self):
        cookie = self.login()
        overview, _ = self.request("GET", "/api/summary", cookie=cookie)
        analytics, payload = self.request("GET", "/api/analytics", cookie=cookie)
        self.assertEqual(overview.status, 200)
        self.assertEqual(analytics.status, 403)
        self.assertIn("error", payload)

    def test_overview_user_cannot_use_other_business_pages(self):
        cookie = self.login()
        for path in ("/api/trend", "/api/rankings", "/api/orders", "/api/chain", "/api/data-quality"):
            response, _ = self.request("GET", path, cookie=cookie)
            expected = 200 if path in {"/api/trend", "/api/rankings"} else 403
            self.assertEqual(response.status, expected, path)


if __name__ == "__main__":
    unittest.main()
