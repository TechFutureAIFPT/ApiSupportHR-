from fastapi.testclient import TestClient

from app.main import app


def test_web_frontend_request_id_header_is_allowed_by_cors() -> None:
    client = TestClient(app)
    response = client.options(
        "/health/live",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "accept,x-request-id",
        },
    )

    assert response.status_code == 200
    allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "x-request-id" in allowed_headers
