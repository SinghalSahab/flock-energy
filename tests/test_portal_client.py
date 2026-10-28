import json
from pathlib import Path
import pytest
import httpx

from src.services.portal_client import PortalClient
from src.models.errors import NotFoundError, PortalAuthenticationError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_portal_client_login_success():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/login"
        assert request.headers.get("origin") == "https://mock-portal.local"
        headers = {
            "set-cookie": "__Secure-better-auth.session_token=test_token_123.sig; Max-Age=3600; Path=/; HttpOnly; Secure; SameSite=Lax",
            "content-type": "application/json",
        }
        return httpx.Response(200, json={"type": "redirect", "status": 303, "location": "/meters"}, headers=headers)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    portal_client = PortalClient(
        base_url="https://mock-portal.local",
        username="test@urja.local",
        password="secretpassword",
        client=client,
    )

    assert not portal_client.is_authenticated()
    portal_client.login()
    assert portal_client.is_authenticated()
    assert portal_client._session_token == "test_token_123.sig"


def test_portal_client_login_invalid_credentials():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"type": "failure", "status": 401, "data": "Invalid credentials"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    portal_client = PortalClient(
        base_url="https://mock-portal.local",
        username="test@urja.local",
        password="wrongpassword",
        client=client,
    )

    with pytest.raises(PortalAuthenticationError):
        portal_client.login()


def test_portal_client_auto_relogin_on_401():
    call_counts = {"login": 0, "energy": 0}

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            call_counts["login"] += 1
            headers = {"set-cookie": "__Secure-better-auth.session_token=fresh_token; Path=/"}
            return httpx.Response(200, json={"type": "redirect"}, headers=headers)

        if request.url.path == "/portal/meters/J100000/energy":
            call_counts["energy"] += 1
            if call_counts["energy"] == 1:
                # First attempt returns 401 session expired
                return httpx.Response(401, json={"error": "unauthorized"})
            # Second attempt succeeds
            return httpx.Response(200, json={"data": [{"timestamp": "23/06/2026 23:30", "kwh": "100.0"}]})

        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    portal_client = PortalClient(
        base_url="https://mock-portal.local",
        username="test@urja.local",
        password="secretpassword",
        client=client,
    )
    # Simulate already having an old token
    portal_client._session_token = "old_token"
    portal_client._session_expiry = 9999999999.0

    readings = portal_client.get_meter_energy("J100000")
    assert len(readings) == 1
    assert readings[0]["kwh"] == "100.0"
    # Verify re-login occurred
    assert call_counts["login"] == 1
    assert call_counts["energy"] == 2


def test_portal_client_404_mapping():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found", "message": "Meter not found"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    portal_client = PortalClient(
        base_url="https://mock-portal.local",
        username="test@urja.local",
        password="secretpassword",
        client=client,
    )
    portal_client._session_token = "valid_token"
    portal_client._session_expiry = 9999999999.0

    with pytest.raises(NotFoundError):
        portal_client.get_meter_energy("NON_EXISTENT")
