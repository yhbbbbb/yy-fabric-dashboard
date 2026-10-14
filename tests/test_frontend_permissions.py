from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


class FrontendPermissionTests(unittest.TestCase):
    def test_sidebar_has_super_admin_management_entry(self):
        self.assertIn('id="admin-entry"', INDEX)
        self.assertIn('href="/admin.html"', INDEX)

    def test_permission_filter_removes_unauthorized_elements_from_layout(self):
        self.assertIn('item.style.display = allowed ? "" : "none"', APP)
        self.assertIn('adminEntry.style.display = isSuperAdmin ? "" : "none"', APP)


if __name__ == "__main__":
    unittest.main()
