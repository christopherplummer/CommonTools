import asyncio
import json
import socket
import sys
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from weather_fishing.config import Settings
from weather_fishing.http import DailyQuota, ProviderError, ProviderHTTP
from weather_fishing.server import create_app


@pytest.mark.parametrize(
    "url",
    [
        "http://api.weather.gov/points/0,0",
        "https://evil.example/",
        "https://api.weather.gov.evil.example/",
        "https://user@api.weather.gov/",
        "https://api.weather.gov:444/",
        "https://127.0.0.1/",
        "https://api.weather.gov/#fragment",
    ],
)
async def test_fixed_provider_origins(url, tmp_path):
    h = ProviderHTTP(Settings(_env_file=None, quota_database=tmp_path / "quota.sqlite3"))
    with pytest.raises(ProviderError, match="Only fixed"):
        await h.get("nws", url)
    await h.close()


async def test_no_redirects_or_credentials_forwarded(tmp_path):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=False)
    h = ProviderHTTP(Settings(_env_file=None, quota_database=tmp_path / "quota"), client)
    with pytest.raises(ProviderError, match="302"):
        await h.get("nws", "https://api.weather.gov/points/0,0")
    assert len(calls) == 1 and "authorization" not in calls[0].headers
    await h.close()


async def test_cache_retrieval_time_and_expiration_directives(tmp_path):
    calls = []

    async def handle(request):
        calls.append(request)
        return httpx.Response(
            200, json={"SYNTHETIC": True}, headers={"cache-control": "max-age=60"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    h = ProviderHTTP(Settings(_env_file=None, quota_database=tmp_path / "quota"), client)
    a = await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    b = await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    assert b.cache_hit and a.retrieved_at == b.retrieved_at and len(calls) == 1
    await h.close()


@pytest.mark.parametrize("control", ["no-store", "no-cache", "private", "max-age=0"])
async def test_cache_respects_restrictions(control, tmp_path):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"SYNTHETIC": True}, headers={"cache-control": control}
            )
        )
    )
    h = ProviderHTTP(Settings(_env_file=None, quota_database=tmp_path / "quota"), client)
    await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    assert not h.cache
    await h.close()


async def test_rate_limit_retry_after_not_ignored(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"retry-after": "120"})

    h = ProviderHTTP(
        Settings(_env_file=None, quota_database=tmp_path / "quota"),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(ProviderError, match="429"):
        await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    with pytest.raises(ProviderError, match="cooldown"):
        await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    assert len(calls) == 1
    await h.close()


async def test_nws_failure_no_rapid_retries(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ConnectError("SYNTHETIC outage")

    h = ProviderHTTP(
        Settings(_env_file=None, quota_database=tmp_path / "quota"),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(ProviderError):
        await h.get("nws", "https://api.weather.gov/test")
    with pytest.raises(ProviderError, match="cooldown"):
        await h.get("nws", "https://api.weather.gov/test")
    assert len(calls) == 1
    await h.close()


async def test_bounded_upstream_bytes(tmp_path):
    h = ProviderHTTP(
        Settings(_env_file=None, quota_database=tmp_path / "quota", max_response_bytes=1000),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 1001))
        ),
    )
    with pytest.raises(ProviderError, match="exceeds"):
        await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    await h.close()


def test_ncei_quota_survives_restart_without_storing_secret(tmp_path):
    path = tmp_path / "quota.sqlite3"
    DailyQuota(path).reserve("SYNTHETIC_SECRET", maximum=1)
    with pytest.raises(ProviderError, match="exhausted"):
        DailyQuota(path).reserve("SYNTHETIC_SECRET", maximum=1)
    assert b"SYNTHETIC_SECRET" not in path.read_bytes()


def test_quota_does_not_assume_provider_midnight_reset(tmp_path):
    import sqlite3

    path = tmp_path / "quota.sqlite3"
    quota = DailyQuota(path)
    quota.reserve("SYNTHETIC_SECRET", maximum=1)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE quota SET day=date(day, '-1 day')")
    with pytest.raises(ProviderError, match="exhausted"):
        quota.reserve("SYNTHETIC_SECRET", maximum=1)


async def test_transient_get_retries_are_bounded(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503)

    h = ProviderHTTP(
        Settings(_env_file=None, quota_database=tmp_path / "quota"),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    with pytest.raises(ProviderError, match="503"):
        await h.get("coops", "https://api.tidesandcurrents.noaa.gov/test")
    assert len(calls) == 3
    await h.close()


async def test_missing_ncei_credentials_no_network(tmp_path):
    calls = []
    h = ProviderHTTP(
        Settings(_env_file=None, quota_database=tmp_path / "quota"),
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))),
    )
    with pytest.raises(ProviderError, match="WF_NCEI_TOKEN"):
        await h.get("ncei", "https://www.ncei.noaa.gov/cdo-web/api/v2/data")
    assert not calls
    await h.close()


async def test_official_sdk_stdio_discovery_and_structured_output():
    root = Path(__file__).resolve().parents[1]
    config = StdioServerParameters(
        command=sys.executable,
        args=["-m", "weather_fishing"],
        cwd=str(root),
        env={"PYTHONPATH": str(root / "src"), "WF_SOLUNAR_PERMISSION_REFERENCE": ""},
    )
    async with stdio_client(config) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools) == 11
            assert all(
                t.inputSchema and t.outputSchema and t.annotations.readOnlyHint for t in tools
            )
            result = await session.call_tool("provider_capabilities", {"provider": "solunar"})
            assert result.structuredContent["records"][0]["values"]["enabled"] is False
            assert len(result.content[0].text) < 120


@pytest.mark.parametrize("override", [None, "false"])
async def test_desktop_launcher_text_results_and_override(override):
    root = Path(__file__).resolve().parents[1]
    env = {
        "PYTHONPATH": str(root / "src"),
        "WF_SOLUNAR_PERMISSION_REFERENCE": "",
        "WF_NCEI_TOKEN": "",
    }
    if override is not None:
        env["WF_TEXT_RESULTS"] = override
    config = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "scripts/run_stdio.py")],
        cwd=str(root.parent),
        env=env,
    )
    async with asyncio.timeout(20):
        async with stdio_client(config) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("provider_capabilities", {"provider": "nws"})
                if override == "false":
                    assert len(result.content[0].text) < 120
                else:
                    payload = json.loads(result.content[0].text)
                    assert payload == result.structuredContent
                    assert payload["records"][0]["values"]["id"] == "nws"
                    unavailable = await session.call_tool(
                        "get_forecast", {"provider": "bom", "location": {"city": "Sydney"}}
                    )
                    failed = json.loads(unavailable.content[0].text)
                    assert failed == unavailable.structuredContent
                    assert failed["status"] == "unavailable" and failed["reasons"]


async def test_http_authentication_and_sdk_roundtrip(service, point):
    from pydantic import SecretStr

    service.settings.api_key = SecretStr("x" * 40)
    service.settings.text_results = True
    service.http.add(
        "/forecast",
        {
            "properties": {
                "periods": [
                    {
                        "startTime": f"2026-10-14T{hour:02d}:00:00Z",
                        "endTime": f"2026-10-14T{hour + 1:02d}:00:00Z",
                        "temperature": 20,
                        "windSpeed": "10 km/h",
                    }
                    for hour in range(4)
                ]
            }
        },
    )
    app = create_app(service.settings, service)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(20)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as client:
            assert (await client.get(base + "/health")).status_code == 200
            assert (await client.post(base + "/mcp/")).status_code == 401
        async with streamable_http_client(
            base + "/mcp/",
            http_client=httpx.AsyncClient(
                headers={"Authorization": "Bearer " + "x" * 40}, timeout=10
            ),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("provider_capabilities", {"provider": "nws"})
                assert result.structuredContent["status"] == "complete"
                result = await session.call_tool(
                    "get_forecast",
                    {"location": point, "fields": ["temperature", "windSpeed"], "limit": 3},
                )
                payload = json.loads(result.content[0].text)
                assert payload == result.structuredContent
                assert payload["status"] == "partial" and len(payload["records"]) == 3
                assert payload["records"][0]["values"] == {
                    "temperature": 20,
                    "windSpeed": "10 km/h",
                }
                assert payload["next_offset"] == 3
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()
