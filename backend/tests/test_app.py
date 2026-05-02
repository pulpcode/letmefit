from fastapi.testclient import TestClient

from app.main import create_app


def test_app_imports() -> None:
    app = create_app()

    assert app.title == "LetMeFit Backend"


def test_health_response_envelope() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok"}
    assert body["request_id"].startswith("req_")
    assert response.headers["x-request-id"] == body["request_id"]


def test_health_uses_incoming_request_id() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/health", headers={"x-request-id": "req_test"})

    assert response.status_code == 200
    assert response.json()["request_id"] == "req_test"
    assert response.headers["x-request-id"] == "req_test"


def test_static_test_page_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/test/")

    assert response.status_code == 200
    assert "LetMeFit API Test" in response.text
