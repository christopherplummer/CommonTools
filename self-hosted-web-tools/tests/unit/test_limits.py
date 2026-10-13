import json

import httpx
import pytest

from web_tools.common.compact import compact_data
from web_tools.common.errors import ToolError
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy


def test_total_response_budget_and_valid_urls():
    data = {
        "text": "x" * 12000,
        "links": [{"url": "https://example.com/" + "y" * 500} for _ in range(30)],
    }
    compact = compact_data(data, 4000, {})
    assert len(json.dumps(compact, separators=(",", ":"))) <= 4000
    assert compact["_truncated"]
    assert compact["links"][0]["url"].endswith("y" * 500)


def test_pagination_budget_preserves_next_offset():
    data = {
        "files": [{"file_id": str(n), "filename": "x" * 500} for n in range(10)],
        "next_offset": None,
    }
    compact = compact_data(data, 2000, {"offset": 20})
    assert compact["next_offset"] == 20 + len(compact["files"])
    assert compact["_truncated"]


@pytest.mark.parametrize("case", ["size", "compression", "redirects"])
async def test_http_limits(settings, case):
    def handler(request):
        if case == "size":
            return httpx.Response(200, content=b"x" * 2000)
        if case == "compression":
            # A streaming body avoids HTTPX eagerly decoding the fixture.
            return httpx.Response(
                200,
                headers={"content-encoding": "gzip"},
                stream=httpx.ByteStream(b"bad compressed body"),
            )
        return httpx.Response(302, headers={"location": "/again"})

    http = SafeHTTPClient(NetworkPolicy(settings), 1, httpx.MockTransport(handler))
    try:
        with pytest.raises(ToolError) as exc:
            await http.read("https://example.com", 1000)
        assert (
            exc.value.code
            == {
                "size": "response_too_large",
                "compression": "unsupported_content_encoding",
                "redirects": "too_many_redirects",
            }[case]
        )
    finally:
        await http.close()
