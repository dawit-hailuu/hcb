"""Authentication service. Verifies credentials and manages users."""
import hashlib
from app.database.db import get_connection


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def authenticate(username: str, password: str):
    """Return user row dict if credentials valid, else None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password_hash = ?",
            (username, _hash(password)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, username, full_name, role, created_at FROM users ORDER BY username"
        ).fetchall()]
    finally:
        conn.close()


def create_user(username: str, password: str, full_name: str, role: str):
    if role not in ("admin", "worker"):
        raise ValueError("role must be 'admin' or 'worker'")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?,?,?,?)",
            (username, _hash(password), full_name, role),
        )
        conn.commit()
    finally:
        conn.close()


def change_password(user_id: int, new_password: str):
    conn = get_connection()
    try:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (_hash(new_password), user_id))
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id: int):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
