from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_configured_browser_origins() -> None:
    """apps/admin and apps/meet call this API cross-origin from a browser
    — confirms CORSMiddleware is actually wired in, not just configured."""
    client = TestClient(app)
    response = client.get(
        "/api/v1/health", headers={"Origin": "http://localhost:3000"}
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unlisted_origins() -> None:
    client = TestClient(app)
    response = client.get(
        "/api/v1/health", headers={"Origin": "https://not-an-allowed-origin.example"}
    )
    assert "access-control-allow-origin" not in response.headers
