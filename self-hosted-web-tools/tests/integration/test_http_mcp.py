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


def test_pdf_rest_download_read_auth_and_schema(settings, search_transport, fixture_site):
    settings.test_allowed_origins = [fixture_site]
    app = create_app(settings, search_transport=search_transport)
    headers = {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"}
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        downloaded = client.post(
            "/api/tools/file_download", headers=headers, json={"url": f"{fixture_site}/manual.pdf"}
        ).json()
        assert downloaded["success"]
        arguments = {"file_id": downloaded["data"]["file_id"], "page_start": 2, "page_end": 2}
        assert client.post("/api/tools/pdf_read", json=arguments).status_code == 401
        read = client.post("/api/tools/pdf_read", headers=headers, json=arguments)
        assert read.status_code == 200 and read.json()["success"]
        assert read.json()["data"]["pages"][0]["text"] == "Second PDF page"
        assert read.json()["data"]["pages"][0]["page_number"] == 2
        for invalid in (
            {"file_id": "../secret"},
            {**arguments, "page_start": 0},
            {**arguments, "path": "C:/secret.pdf"},
        ):
            assert (
                client.post("/api/tools/pdf_read", headers=headers, json=invalid).status_code == 422
            )
        failed = client.post(
            "/api/tools/pdf_read", headers=headers, json={**arguments, "page_end": 1}
        )
        assert failed.status_code == 400 and failed.json()["error"]["code"] == "invalid_page_range"
