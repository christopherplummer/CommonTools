import socket

import httpx
import pytest

from web_tools.common.errors import ToolError
from web_tools.security.http_client import PinnedBackend, SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy


async def test_connection_uses_validated_ip_not_hostname(settings, monkeypatch):
    policy = NetworkPolicy(settings)
    backend = PinnedBackend(policy)
    resolved = []
    connected = []

    async def resolve(host, port, *, test_exception=False):
        resolved.append((host, port))
        return ["93.184.215.14"]

    async def connect(host, port, *args):
        connected.append((host, port))
        return "connection"

    monkeypatch.setattr(policy, "resolve", resolve)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    assert await backend.connect_tcp("example.com", 443) == "connection"
    assert resolved == [("example.com", 443)]
    assert connected == [("93.184.215.14", 443)]


async def test_mixed_public_private_dns_fails_closed(settings, monkeypatch):
    import asyncio

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80)),
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(ToolError, match="non-public"):
        await NetworkPolicy(settings).resolve("example.com", 80)


async def test_dns_rebinding_rechecked_for_each_connection(settings, monkeypatch):
    policy = NetworkPolicy(settings)
    backend = PinnedBackend(policy)
    import asyncio

    addresses = iter(["93.184.215.14", "127.0.0.1"])
    connected = []

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (next(addresses), 443))]

    async def connect(host, port, *args):
        connected.append(host)
        return "connection"

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(backend.backend, "connect_tcp", connect)
    await backend.connect_tcp("rebind.example", 443)
    with pytest.raises(ToolError):
        await backend.connect_tcp("rebind.example", 443)
    assert connected == ["93.184.215.14"]


async def test_http_client_does_not_share_cookies(settings):
    sent_cookies = []

    def handler(request):
        sent_cookies.append(request.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "account=secret; Path=/"}, text="ok")

    http = SafeHTTPClient(NetworkPolicy(settings), 1, httpx.MockTransport(handler))
    try:
        await http.read("https://example.com", 100)
        await http.read("https://example.com", 100)
        assert sent_cookies == [None, None]
    finally:
        await http.close()
