import os
import tempfile
import unittest
from pathlib import Path

from backend import admin_auth


class AdminAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        admin_auth.ADMIN_DB_PATH = Path(self.temp_dir.name) / "admin.sqlite"
        os.environ["YY_ADMIN_PASSWORD"] = "TestAdmin@123"
        admin_auth.init_admin_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_admin_is_super_admin_with_all_permissions(self):
        user = admin_auth.authenticate("admin", "TestAdmin@123")
        self.assertIsNotNone(user)
        self.assertEqual(user["roles"], ["super_admin"])
        self.assertEqual(set(user["permissions"]), set(admin_auth.PERMISSION_CODES))
        self.assertTrue(admin_auth.user_is_super_admin(user))

    def test_user_inherits_union_of_active_roles(self):
        overview = admin_auth.create_role(
            "看板浏览",
            "dashboard_viewer",
            "查看总览和订单",
            ["overview", "orders"],
        )
        analytics = admin_auth.create_role(
            "经营分析",
            "business_analyst",
            "查看经营分析",
            ["analytics"],
        )
        user = admin_auth.create_user(
            "alice",
            "Alice@123",
            [overview["id"], analytics["id"]],
        )
        self.assertEqual(
            set(user["permissions"]),
            {"overview", "orders", "analytics"},
        )

    def test_inactive_role_is_not_inherited(self):
        role = admin_auth.create_role("临时角色", "temporary", "", ["quality"])
        user = admin_auth.create_user("bob", "Bob@12345", [role["id"]])
        self.assertEqual(user["permissions"], ["quality"])
        admin_auth.update_role(
            role["id"],
            role["name"],
            role["code"],
            role["description"],
            role["permissions"],
            False,
        )
        refreshed = admin_auth.get_user(user["id"])
        self.assertEqual(refreshed["permissions"], [])

    def test_session_is_invalid_after_delete(self):
        user = admin_auth.authenticate("admin", "TestAdmin@123")
        token = admin_auth.create_session(user["id"])
        headers = {"Cookie": f"{admin_auth.SESSION_COOKIE}={token}"}
        self.assertEqual(
            admin_auth.user_from_headers(headers)["username"],
            "admin",
        )
        admin_auth.delete_session(token)
        self.assertIsNone(admin_auth.user_from_headers(headers))

    def test_last_super_admin_cannot_be_disabled_or_deleted(self):
        admin = admin_auth.get_user_by_username("admin")
        with self.assertRaises(ValueError):
            admin_auth.update_user(admin["id"], [], False)
        with self.assertRaises(ValueError):
            admin_auth.delete_user(admin["id"])

    def test_password_is_not_stored_as_plaintext(self):
        with admin_auth._connect() as conn:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM users WHERE username = 'admin'"
            ).fetchone()
        self.assertNotEqual(row["password_hash"], "TestAdmin@123")
        self.assertNotEqual(row["password_salt"], "TestAdmin@123")


if __name__ == "__main__":
    unittest.main()
