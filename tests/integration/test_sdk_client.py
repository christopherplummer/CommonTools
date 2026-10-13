import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from web_tools.main import create_app


@pytest.mark.integration
async def test_official_sdk_client(settings, search_transport):
    app = create_app(settings, search_transport=search_transport)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers={"Authorization": f"Bearer {settings.api_key.get_secret_value()}"},
        ) as http:
            async with streamable_http_client(
                "http://127.0.0.1:8000/mcp", http_client=http
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} >= {
                        "web_search",
                        "web_fetch",
                        "file_download",
                        "file_inspect",
                        "file_list",
                    }
                    result = await session.call_tool("web_search", {"query": "docs", "limit": 1})
                    assert not result.isError
                    assert result.structuredContent["data"]["results"][0]["title"] == "Example"
                    error = await session.call_tool("web_search", {"query": "docs", "limit": 100})
                    assert error.isError
                    assert error.structuredContent["error"]["code"] == "invalid_arguments"
