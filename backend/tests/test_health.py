"""System endpoint tests."""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health_reports_process_liveness() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_unavailable_without_model() -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "model_not_loaded",
    }
