"""Tests for the FastAPI application.

Verifies:
- Server starts and responds to requests
- Hello endpoint returns expected response
"""

from fastapi.testclient import TestClient

from api.app import create_app


class TestHelloEndpoint:
    def test_hello_returns_greeting(self) -> None:
        """Test that /hello endpoint returns the correct message."""
        app = create_app()
        client = TestClient(app)

        response = client.get("/hello")

        assert response.status_code == 200
        assert response.json() == {"message": "Hello, world!"}

    def test_hello_returns_json_content_type(self) -> None:
        """Test that /hello endpoint returns JSON content type."""
        app = create_app()
        client = TestClient(app)

        response = client.get("/hello")

        assert response.headers["content-type"] == "application/json"
