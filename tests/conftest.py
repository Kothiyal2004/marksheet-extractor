"""Shared pytest fixtures."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

# ---------------------------------------------------------------------------
# Override settings so tests never need a real .env / Gemini key
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    GEMINI_API_KEY="test-gemini-key-not-real",
    SECRET_KEY="test-secret-key-minimum-32-characters-here",
    ALGORITHM="HS256",
    ACCESS_TOKEN_EXPIRE_MINUTES=30,
    API_USERNAME="testuser",
    API_PASSWORD="testpass",
    GEMINI_MODEL="gemini-1.5-flash",
)


@pytest.fixture(autouse=True)
def override_settings():
    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client: TestClient):
    resp = client.post(
        "/auth/token",
        data={"username": "testuser", "password": "testpass"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
