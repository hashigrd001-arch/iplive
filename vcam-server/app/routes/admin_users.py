"""Admin-user management endpoints.

The first admin can still be bootstrapped by CLI / environment, but
once the web panel is live the owner needs a non-technical way to add
more operators who can issue license keys. These endpoints stay small:
list active/inactive admins and create a new active admin with a bcrypt
password hash. Password reset / deactivation can be added later without
changing the table schema.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import auth, db
from ..auth import AdminUser

router = APIRouter(tags=["admin"])


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "display_name": row["display_name"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "is_active": bool(row["is_active"]),
    }


@router.get("/api/admin/admins")
def list_admins(
    admin: AdminUser = Depends(auth.current_admin),
) -> list[dict[str, Any]]:
    """Return admin users newest-first for the web console."""
    with db.connect() as cx:
        rows = cx.execute(
            "SELECT id, email, display_name, created_at, last_login_at, "
            "is_active FROM admins ORDER BY id DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("/api/admin/admins")
def create_admin(
    payload: dict[str, Any],
    admin: AdminUser = Depends(auth.current_admin),
) -> dict[str, Any]:
    """Create another admin account from the web console.

    Body:
      * ``email``        — login handle, unique.
      * ``password``     — plaintext only in-flight; stored as bcrypt.
      * ``display_name`` — optional friendly name.
    """
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    display_name = str(payload.get("display_name") or "").strip() or email

    if "@" not in email or "." not in email:
        raise HTTPException(400, "email ไม่ถูกต้อง")
    try:
        pwd_hash = auth.hash_password(password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    with db.connect() as cx:
        existing = cx.execute(
            "SELECT id FROM admins WHERE email = ?", (email,),
        ).fetchone()
        if existing:
            raise HTTPException(409, "admin email already exists")
        cur = cx.execute(
            "INSERT INTO admins (email, password_hash, display_name, "
            "created_at, is_active) VALUES (?, ?, ?, ?, 1)",
            (email, pwd_hash, display_name, db.now_iso()),
        )
        row = cx.execute(
            "SELECT id, email, display_name, created_at, last_login_at, "
            "is_active FROM admins WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()

    auth.write_audit(
        admin, "admin.create", "admin", int(cur.lastrowid or 0), email,
    )
    return _row_to_dict(row)
