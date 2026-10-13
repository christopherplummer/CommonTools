import httpx
import pytest

from web_tools.common.errors import ToolError
from web_tools.services.search_service import SearchService


async def test_blocked_engines_are_not_reported_as_empty_success(settings):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"results": [], "unresponsive_engines": [["duckduckgo", "CAPTCHA"]]}
            )
        )
    ) as client:
        service = SearchService(settings, client)
        with pytest.raises(ToolError) as error:
            await service.search("docs")
        assert error.value.code == "search_engines_unavailable"
        assert error.value.retryable and "CAPTCHA" in error.value.message
        assert not await service.ready()


async def test_partial_results_include_upstream_warnings(settings):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "results": [{"url": "https://example.com", "title": "Example"}],
                    "unresponsive_engines": [["duckduckgo", "CAPTCHA"]],
                },
            )
        )
    ) as client:
        result = await SearchService(settings, client).search("docs")
        assert result["results"]
        assert result["warnings"] == [{"engine": "duckduckgo", "reason": "CAPTCHA"}]
