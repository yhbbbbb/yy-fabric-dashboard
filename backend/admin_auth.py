from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN_DB_PATH = ROOT / "data" / "admin.sqlite"
SESSION_COOKIE = "yy_session"
SESSION_HOURS = 12

PERMISSIONS = {
    "overview": "总览看板",
    "chain": "链路分析",
    "analytics": "经营分析",
    "orders": "订单查询",
    "quality": "数据质量",
    "admin": "系统管理",
}
PERMISSION_CODES = tuple(PERMISSIONS)
ROLE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class _AdminConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    ADMIN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ADMIN_DB_PATH, factory=_AdminConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        210_000,
    ).hex()


def _verify_password(password: str, salt_hex: str, expected: str) -> bool:
    try:
        actual = _password_hash(password, bytes.fromhex(salt_hex))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


def _permission_values(codes) -> list[str]:
    return sorted(set(codes or []).intersection(PERMISSION_CODES))


def _validate_role_code(code: str) -> str:
    code = str(code or "").strip()
    if not ROLE_CODE_RE.fullmatch(code):
        raise ValueError("角色编码必须是 2-49 位小写字母、数字或下划线，且以字母开头")
    return code


def init_admin_db() -> None:
    default_password = os.environ.get("YY_ADMIN_PASSWORD")
    if not default_password:
        raise RuntimeError("Set YY_ADMIN_PASSWORD before initializing the admin database.")
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                system_role INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS permissions (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS role_permissions (
                role_id INTEGER NOT NULL,
                permission_code TEXT NOT NULL,
                PRIMARY KEY (role_id, permission_code),
                FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
                FOREIGN KEY (permission_code) REFERENCES permissions(code) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO permissions (code, name, description) VALUES (?, ?, ?)",
            [(code, label, f"允许访问{label}") for code, label in PERMISSIONS.items()],
        )
        now = _iso(_now())
        for name, code, description, permission_codes in (
            ("超级管理员", "super_admin", "管理用户、角色和全部页面", PERMISSION_CODES),
            ("普通用户", "viewer", "按授权查看业务页面", ()),
        ):
            role = conn.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()
            if role is None:
                role_id = conn.execute(
                    """
                    INSERT INTO roles
                        (name, code, description, active, system_role, created_at, updated_at)
                    VALUES (?, ?, ?, 1, 1, ?, ?)
                    """,
                    (name, code, description, now, now),
                ).lastrowid
            else:
                role_id = role["id"]
            if code == "super_admin":
                conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
                    [(role_id, permission) for permission in PERMISSION_CODES],
                )
        admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if admin is None:
            salt = secrets.token_bytes(16)
            user_id = conn.execute(
                """
                INSERT INTO users
                    (username, password_hash, password_salt, active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                ("admin", _password_hash(default_password, salt), salt.hex(), now),
            ).lastrowid
        else:
            user_id = admin["id"]
        super_role = conn.execute(
            "SELECT id FROM roles WHERE code = 'super_admin'"
        ).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, super_role["id"]),
        )


def _role_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    permissions = [
        item["permission_code"]
        for item in conn.execute(
            "SELECT permission_code FROM role_permissions WHERE role_id = ? ORDER BY permission_code",
            (row["id"],),
        ).fetchall()
    ]
    if row["code"] == "super_admin":
        permissions = list(PERMISSION_CODES)
    user_count = conn.execute(
        "SELECT COUNT(*) AS count FROM user_roles WHERE role_id = ?",
        (row["id"],),
    ).fetchone()["count"]
    return {
        "id": row["id"],
        "name": row["name"],
        "code": row["code"],
        "description": row["description"],
        "active": bool(row["active"]),
        "system_role": bool(row["system_role"]),
        "permissions": permissions,
        "user_count": user_count,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _user_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    roles = conn.execute(
        """
        SELECT r.id, r.name, r.code, r.active, r.system_role
        FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = ? ORDER BY r.code
        """,
        (row["id"],),
    ).fetchall()
    permissions: set[str] = set()
    for role in roles:
        if role["code"] == "super_admin":
            permissions.update(PERMISSION_CODES)
        elif role["active"]:
            permissions.update(
                item["permission_code"]
                for item in conn.execute(
                    "SELECT permission_code FROM role_permissions WHERE role_id = ?",
                    (role["id"],),
                ).fetchall()
            )
    return {
        "id": row["id"],
        "username": row["username"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "roles": [role["code"] for role in roles],
        "role_ids": [role["id"] for role in roles],
        "role_names": [role["name"] for role in roles],
        "permissions": sorted(permissions),
    }


def get_user(user_id: int) -> dict | None:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _user_dict(conn, row) if row else None


def get_user_by_username(username: str) -> dict | None:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        return _user_dict(conn, row) if row else None


def authenticate(username: str, password: str) -> dict | None:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username.strip(),),
        ).fetchone()
        if row is None or not _verify_password(
            password, row["password_salt"], row["password_hash"]
        ):
            return None
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_iso(_now()), row["id"]),
        )
        refreshed = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return _user_dict(conn, refreshed)


def create_session(user_id: int) -> str:
    init_admin_db()
    token = secrets.token_urlsafe(36)
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, _iso(now + timedelta(hours=SESSION_HOURS)), _iso(now)),
        )
    return token


def _cookie_value(cookie_header: str, name: str) -> str | None:
    for item in cookie_header.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator and key == name:
            return value
    return None


def session_token(headers) -> str | None:
    return _cookie_value(headers.get("Cookie", ""), SESSION_COOKIE)


def user_from_headers(headers) -> dict | None:
    init_admin_db()
    token = session_token(headers)
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND u.active = 1 AND s.expires_at > ?
            """,
            (token, _iso(_now())),
        ).fetchone()
        if row is None:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return _user_dict(conn, row)


def delete_session(token: str | None) -> None:
    if token:
        with _connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_has_permission(user: dict | None, permission: str) -> bool:
    return bool(user and permission in user.get("permissions", []))


def user_is_super_admin(user: dict | None) -> bool:
    return bool(user and "super_admin" in user.get("roles", []))


def list_users() -> list[dict]:
    init_admin_db()
    with _connect() as conn:
        return [
            _user_dict(conn, row)
            for row in conn.execute("SELECT * FROM users ORDER BY username").fetchall()
        ]


def list_roles() -> list[dict]:
    init_admin_db()
    with _connect() as conn:
        return [
            _role_dict(conn, row)
            for row in conn.execute("SELECT * FROM roles ORDER BY system_role DESC, name").fetchall()
        ]


def _role_ids(conn: sqlite3.Connection, role_ids) -> list[int]:
    values = sorted({int(value) for value in (role_ids or [])})
    if not values:
        return []
    placeholders = ",".join("?" for _ in values)
    rows = conn.execute(
        f"SELECT id FROM roles WHERE id IN ({placeholders}) AND active = 1",
        values,
    ).fetchall()
    if len(rows) != len(values):
        raise ValueError("只能分配存在且启用的角色")
    return values


def _assert_super_admin_survives(
    conn: sqlite3.Connection,
    user_id: int,
    role_ids: list[int],
    active: bool,
) -> None:
    current = conn.execute(
        """
        SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
        WHERE ur.user_id = ? AND r.code = 'super_admin'
        """,
        (user_id,),
    ).fetchone()
    will_be_super = bool(
        active
        and conn.execute(
            """
            SELECT 1 FROM roles
            WHERE id IN ({}) AND code = 'super_admin'
            """.format(",".join("?" for _ in role_ids) or "NULL"),
            role_ids,
        ).fetchone()
    )
    if current and not will_be_super:
        count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM users u JOIN user_roles ur ON ur.user_id = u.id
            JOIN roles r ON r.id = ur.role_id
            WHERE u.active = 1 AND r.code = 'super_admin'
            """
        ).fetchone()["count"]
        if count <= 1:
            raise ValueError("至少需要保留一个启用的超级管理员")


def create_user(username: str, password: str, role_ids, active: bool = True) -> dict:
    username = str(username or "").strip()
    if not username or len(username) > 80:
        raise ValueError("用户名不能为空且不能超过 80 个字符")
    if len(password or "") < 8:
        raise ValueError("密码至少需要 8 个字符")
    init_admin_db()
    salt = secrets.token_bytes(16)
    with _connect() as conn:
        role_ids = _role_ids(conn, role_ids)
        try:
            user_id = conn.execute(
                """
                INSERT INTO users
                    (username, password_hash, password_salt, active, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, _password_hash(password, salt), salt.hex(), int(active), _iso(_now())),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在") from exc
        conn.executemany(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            [(user_id, role_id) for role_id in role_ids],
        )
        return _user_dict(conn, conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def update_user(user_id: int, role_ids, active: bool, password: str | None = None) -> dict:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("用户不存在")
        role_ids = _role_ids(conn, role_ids)
        _assert_super_admin_survives(conn, user_id, role_ids, active)
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (int(active), user_id))
        conn.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            [(user_id, role_id) for role_id in role_ids],
        )
        if password:
            if len(password) < 8:
                raise ValueError("密码至少需要 8 个字符")
            salt = secrets.token_bytes(16)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (_password_hash(password, salt), salt.hex(), user_id),
            )
        return _user_dict(conn, conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def delete_user(user_id: int) -> None:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("用户不存在")
        user = _user_dict(conn, row)
        if user["username"] == "admin":
            raise ValueError("默认 admin 账号不能删除")
        _assert_super_admin_survives(conn, user_id, [], False)
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def create_role(
    name: str,
    code: str,
    description: str,
    permission_codes,
    active: bool = True,
) -> dict:
    name = str(name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("角色名称不能为空且不能超过 80 个字符")
    code = _validate_role_code(code)
    if code in {"super_admin", "viewer"}:
        raise ValueError("系统角色编码不能重复使用")
    init_admin_db()
    now = _iso(_now())
    with _connect() as conn:
        try:
            role_id = conn.execute(
                """
                INSERT INTO roles
                    (name, code, description, active, system_role, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (name, code, str(description or "").strip(), int(active), now, now),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("角色编码已存在") from exc
        conn.executemany(
            "INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
            [(role_id, permission) for permission in _permission_values(permission_codes)],
        )
        return _role_dict(conn, conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone())


def update_role(
    role_id: int,
    name: str,
    code: str,
    description: str,
    permission_codes,
    active: bool,
) -> dict:
    init_admin_db()
    name = str(name or "").strip()
    if not name or len(name) > 80:
        raise ValueError("角色名称不能为空且不能超过 80 个字符")
    code = _validate_role_code(code)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if row is None:
            raise ValueError("角色不存在")
        if row["system_role"]:
            if row["code"] == "super_admin" and (
                not active or set(permission_codes or []) != set(PERMISSION_CODES)
            ):
                raise ValueError("超级管理员角色必须保持启用并拥有全部页面权限")
            if code != row["code"]:
                raise ValueError("系统角色编码不能修改")
        now = _iso(_now())
        try:
            conn.execute(
                """
                UPDATE roles
                SET name = ?, code = ?, description = ?, active = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, code, str(description or "").strip(), int(active), now, role_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("角色编码已存在") from exc
        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        permissions = PERMISSION_CODES if row["code"] == "super_admin" else _permission_values(permission_codes)
        conn.executemany(
            "INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)",
            [(role_id, permission) for permission in permissions],
        )
        return _role_dict(conn, conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone())


def delete_role(role_id: int) -> None:
    init_admin_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if row is None:
            raise ValueError("角色不存在")
        if row["system_role"]:
            raise ValueError("系统角色不能删除")
        binding = conn.execute(
            "SELECT 1 FROM user_roles WHERE role_id = ? LIMIT 1", (role_id,)
        ).fetchone()
        if binding:
            raise ValueError("角色仍有用户绑定，请先解除绑定")
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
