from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PublicRepositorySafetyTests(unittest.TestCase):
    def test_repository_ignores_business_data_and_local_databases(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.xlsx", "*.csv", "*.pkl", "data/*", "output/", "raw_data/"):
            self.assertIn(pattern, gitignore)

    def test_public_files_have_no_real_data_artifacts(self):
        forbidden_suffixes = {".xlsx", ".xls", ".csv", ".pkl", ".sqlite", ".jpg"}
        artifacts = [
            path for path in ROOT.rglob("*")
            if path.is_file()
            and path.suffix.lower() in forbidden_suffixes
            and path.parent.name != "data"
        ]
        self.assertEqual(artifacts, [])

    def test_public_docs_have_no_default_password_or_windows_path(self):
        text_files = [
            path for path in ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".py", ".ps1", ".js", ".html"}
        ]
        content = "\n".join(path.read_text(encoding="utf-8") for path in text_files)
        self.assertNotIn("Admin@" + "123456", content)
        self.assertNotRegex(content, re.compile(r"C:\\Users\\PC", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
