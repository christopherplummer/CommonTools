import ipaddress

import httpx
import pytest

from web_tools.common.errors import ToolError
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://localhost",
        "http://127.0.0.1",
        "http://127.1",
        "http://2130706433",
        "http://10.0.0.1",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://user:password@example.com",
        "http://example.com:22",
        "http://[fe80::1%25eth0]",
        "http://0.0.0.0",
    ],
)
async def test_block_internal(settings, url):
    with pytest.raises(ToolError):
        await NetworkPolicy(settings).check(url)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "::ffff:10.0.0.1", "64:ff9b::a00:1"],
)
def test_private_ip_classification(address):
    assert not NetworkPolicy.is_public(ipaddress.ip_address(address))


async def test_redirect_policy(settings):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/metadata"})
    )
    http = SafeHTTPClient(NetworkPolicy(settings), 1, transport)
    try:
        with pytest.raises(ToolError, match="Non-public"):
            await http.read("https://example.com", 1000)
    finally:
        await http.close()


def test_test_exceptions_forbidden_in_production(settings):
    with pytest.raises(ValueError, match="only with ENVIRONMENT=test"):
        type(settings)(api_key=settings.api_key, test_allowed_origins=["http://127.0.0.1:8001"])
