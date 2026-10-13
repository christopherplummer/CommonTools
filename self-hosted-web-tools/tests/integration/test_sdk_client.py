import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from web_tools.main import create_app


@pytest.mark.integration
async def test_official_sdk_client(settings, search_transport, fixture_site):
    settings.test_allowed_origins = [fixture_site]
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
                        "pdf_read",
                    }
                    result = await session.call_tool("web_search", {"query": "docs", "limit": 1})
                    assert not result.isError
                    assert result.structuredContent["data"]["results"][0]["title"] == "Example"
                    error = await session.call_tool("web_search", {"query": "docs", "limit": 100})
                    assert error.isError
                    assert error.structuredContent["error"]["code"] == "invalid_arguments"
                    downloaded = await session.call_tool(
                        "file_download", {"url": f"{fixture_site}/manual.pdf"}
                    )
                    assert not downloaded.isError
                    read = await session.call_tool(
                        "pdf_read", {"file_id": downloaded.structuredContent["data"]["file_id"]}
                    )
                    assert not read.isError
                    assert [page["text"] for page in read.structuredContent["data"]["pages"]] == [
                        "First PDF page",
                        "Second PDF page",
                    ]
                    invalid = await session.call_tool("pdf_read", {"file_id": "../../secret"})
                    assert invalid.isError
                    assert invalid.structuredContent["error"]["code"] == "invalid_arguments"
