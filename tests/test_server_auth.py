import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from backend import admin_auth, server


class ServerAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        admin_auth.ADMIN_DB_PATH = Path(cls.temp_dir.name) / "admin.sqlite"
        os.environ["YY_ADMIN_PASSWORD"] = "TestAdmin@123"
        admin_auth.init_admin_db()
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
        parsed = json.loads(content) if content else None
        return response, parsed

    def test_business_api_requires_login(self):
        response, payload = self.request("GET", "/api/summary")
        self.assertEqual(response.status, 401)
        self.assertIn("error", payload)

    def test_login_sets_cookie_and_returns_user(self):
        response, payload = self.request(
            "POST",
            "/api/auth/login",
            {"username": "admin", "password": "TestAdmin@123"},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["user"]["username"], "admin")
        self.assertIn("super_admin", payload["user"]["roles"])
        self.assertTrue(response.getheader("Set-Cookie").startswith("yy_session="))

    def test_invalid_credentials_are_unauthorized(self):
        response, payload = self.request(
            "POST",
            "/api/auth/login",
            {"username": "admin", "password": "wrong-password"},
        )
        self.assertEqual(response.status, 401)
        self.assertIn("error", payload)

    def test_admin_routes_require_super_admin(self):
        viewer_role = admin_auth.create_role(
            "仅总览",
            "overview_only",
            "",
            ["overview"],
        )
        admin_auth.create_user("viewer", "Viewer@123", [viewer_role["id"]])
        login, logged_in = self.request(
            "POST",
            "/api/auth/login",
            {"username": "viewer", "password": "Viewer@123"},
        )
        cookie = login.getheader("Set-Cookie").split(";", 1)[0]
        self.assertEqual(logged_in["user"]["permissions"], ["overview"])
        response, payload = self.request("GET", "/api/admin/users", cookie=cookie)
        self.assertEqual(response.status, 403)
        self.assertIn("error", payload)

    def test_admin_can_create_role_and_user(self):
        login, _ = self.request(
            "POST",
            "/api/auth/login",
            {"username": "admin", "password": "TestAdmin@123"},
        )
        cookie = login.getheader("Set-Cookie").split(";", 1)[0]
        role_response, role_payload = self.request(
            "POST",
            "/api/admin/roles/create",
            {
                "name": "订单查看",
                "code": "order_viewer",
                "description": "只看订单",
                "permissions": ["orders"],
            },
            cookie=cookie,
        )
        self.assertEqual(role_response.status, 200)
        role_id = role_payload["role"]["id"]
        user_response, user_payload = self.request(
            "POST",
            "/api/admin/users/create",
            {
                "username": "orders-user",
                "password": "Orders@123",
                "role_ids": [role_id],
            },
            cookie=cookie,
        )
        self.assertEqual(user_response.status, 200)
        self.assertEqual(user_payload["user"]["permissions"], ["orders"])

    def test_logout_invalidates_cookie(self):
        login, _ = self.request(
            "POST",
            "/api/auth/login",
            {"username": "admin", "password": "TestAdmin@123"},
        )
        cookie = login.getheader("Set-Cookie").split(";", 1)[0]
        logout, _ = self.request("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(logout.status, 200)
        response, payload = self.request("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(response.status, 401)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
