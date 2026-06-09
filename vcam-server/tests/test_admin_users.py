"""Admin-user management endpoints."""
from __future__ import annotations


def test_admin_users_requires_cookie(client):
    resp = client.get("/api/admin/admins")
    assert resp.status_code == 401


def test_create_admin_then_login_with_new_account(admin_client):
    resp = admin_client.post(
        "/api/admin/admins",
        json={
            "email": "ops@example.com",
            "password": "strong-pass-123",
            "display_name": "Ops Admin",
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["email"] == "ops@example.com"
    assert created["display_name"] == "Ops Admin"
    assert created["is_active"] is True
    assert "password" not in created

    rows = admin_client.get("/api/admin/admins").json()
    assert [r["email"] for r in rows][:2] == [
        "ops@example.com",
        "test@example.com",
    ]

    admin_client.post("/admin/logout", follow_redirects=False)
    login = admin_client.post(
        "/admin/login",
        data={"email": "ops@example.com", "password": "strong-pass-123"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert admin_client.get("/api/admin/licenses").status_code == 200


def test_create_admin_rejects_duplicate_email(admin_client):
    payload = {
        "email": "ops@example.com",
        "password": "strong-pass-123",
        "display_name": "Ops",
    }
    assert admin_client.post("/api/admin/admins", json=payload).status_code == 200
    resp = admin_client.post("/api/admin/admins", json=payload)
    assert resp.status_code == 409


def test_create_admin_rejects_short_password(admin_client):
    resp = admin_client.post(
        "/api/admin/admins",
        json={"email": "ops@example.com", "password": "short"},
    )
    assert resp.status_code == 400
