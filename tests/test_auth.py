"""Tests for JWT authentication endpoints."""

from fastapi.testclient import TestClient


def test_login_success(client: TestClient):
    resp = client.post(
        "/auth/token",
        data={"username": "testuser", "password": "testpass"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60  # 30 min × 60 s


def test_login_wrong_password(client: TestClient):
    resp = client.post(
        "/auth/token",
        data={"username": "testuser", "password": "wrongpass"},
    )
    assert resp.status_code == 401


def test_login_wrong_username(client: TestClient):
    resp = client.post(
        "/auth/token",
        data={"username": "nobody", "password": "testpass"},
    )
    assert resp.status_code == 401


def test_protected_endpoint_no_token(client: TestClient):
    """Extraction endpoint must reject requests without a token."""
    resp = client.post("/api/v1/extract")
    assert resp.status_code == 401


def test_protected_endpoint_bad_token(client: TestClient):
    resp = client.post(
        "/api/v1/extract",
        headers={"Authorization": "Bearer totally.invalid.token"},
    )
    assert resp.status_code == 401


def test_health_endpoint(client: TestClient):
    assert client.get("/health").status_code == 200


def test_root_endpoint(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
