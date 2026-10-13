import httpx
import pytest

from web_tools.common.errors import ToolError
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy
from web_tools.services.fetch_service import FetchService
from web_tools.services.search_service import SearchService


async def test_search_normalization(settings, search_transport):
    async with httpx.AsyncClient(transport=search_transport) as client:
        result = await SearchService(settings, client).search("docs", limit=1)
        assert result["results"] == [
            {
                "title": "Example",
                "url": "https://example.com",
                "snippet": "A snippet",
                "engine": "fixture",
            }
        ]
        assert result["_truncated"]


@pytest.mark.parametrize("payload", [{"results": []}, {}])
async def test_empty_search(settings, payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        assert (await SearchService(settings, client).search("docs"))["results"] == []


@pytest.mark.parametrize("status,retryable", [(403, False), (429, True), (503, True)])
async def test_search_http_errors(settings, status, retryable):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status))
    ) as client:
        with pytest.raises(ToolError) as exc:
            await SearchService(settings, client).search("docs")
        assert exc.value.retryable == retryable


async def test_extract_and_truncate(settings):
    body = '<html><title>A title</title><link rel="canonical" href="/canonical"><main><p>'
    body += "Readable documentation. " * 100
    body += '</p><a href="/guide">Guide</a><script>SECRET_SCRIPT</script></main></html>'
    http = SafeHTTPClient(
        NetworkPolicy(settings),
        1,
        httpx.MockTransport(
            lambda r: httpx.Response(200, text=body, headers={"content-type": "text/html"})
        ),
    )
    try:
        result = await FetchService(settings, http).fetch("https://example.com", 100)
        assert result["title"] == "A title"
        assert result["canonical_url"] == "https://example.com/canonical"
        assert len(result["text"]) == 100 and result["_truncated"]
        assert "SECRET_SCRIPT" not in result["text"]
        assert result["links"][0]["url"] == "https://example.com/guide"
    finally:
        await http.close()
