from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import admin_auth


if __name__ == "__main__":
    admin_auth.init_admin_db()
    print(f"Initialized {admin_auth.ADMIN_DB_PATH}")
    print("Default username: admin")
    print("Set YY_ADMIN_PASSWORD before initialization to choose the initial password.")
