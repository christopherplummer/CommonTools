import json

import httpx
import pytest
from fastapi.testclient import TestClient

from web_tools.main import create_app
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy
from web_tools.services.fetch_service import FetchService


def test_health_auth_and_rest(settings, search_transport):
    app = create_app(settings, search_transport=search_transport)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        assert client.post("/api/tools/web_search", json={"query": "docs"}).status_code == 401
        headers = {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"}
        result = client.post("/api/tools/web_search", headers=headers, json={"query": "docs"})
        assert result.json()["success"]
        assert (
            client.post(
                "/api/tools/web_search", headers=headers, json={"query": "docs", "limit": 999}
            ).status_code
            == 422
        )


def test_readiness_fails_on_upstream(settings):
    app = create_app(settings, search_transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_mcp_initialize_discovery_invocation(settings, search_transport):
    app = create_app(settings, search_transport=search_transport)
    headers = {
        "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Accept": "application/json, text/event-stream",
    }
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        init = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        assert init.status_code == 200, init.text
        assert init.json()["result"]["serverInfo"]["name"] == "self-hosted-web-tools"
        listed = client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        ).json()
        assert {t["name"] for t in listed["result"]["tools"]} >= {"web_search", "web_fetch"}
        result = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "web_search", "arguments": {"query": "docs"}},
            },
        ).json()
        assert not result["result"]["isError"]
        assert json.loads(result["result"]["content"][0]["text"])["success"]
        result = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "web_fetch", "arguments": {"url": "http://127.0.0.1"}},
            },
        ).json()
        assert result["result"]["isError"]


@pytest.mark.integration
async def test_real_http_and_redirects(settings, fixture_site):
    settings.test_allowed_origins = [fixture_site]
    http = SafeHTTPClient(NetworkPolicy(settings), 5)
    try:
        result = await FetchService(settings, http).fetch(f"{fixture_site}/redirect")
        assert result["title"] == "Fixture Docs"
        assert result["source_url"].endswith("/docs")
        with pytest.raises(Exception, match="Non-public"):
            await http.read(f"{fixture_site}/private-redirect", 1000)
    finally:
        await http.close()
