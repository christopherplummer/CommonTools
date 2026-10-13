"""Unit preferences tested with synthetic provider data and actual MCP discovery."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from weather_fishing.config import Settings


@pytest.mark.parametrize("units", ["metric", "imperial", "source"])
def test_environment_unit_preference(monkeypatch, units):
    monkeypatch.setenv("WF_DEFAULT_UNITS", units)
    assert Settings(_env_file=None).default_units == units


def test_invalid_environment_preference_rejected(monkeypatch):
    monkeypatch.setenv("WF_DEFAULT_UNITS", "invalid")
    with pytest.raises(ValidationError, match="default_units"):
        Settings(_env_file=None)


async def test_default_forecast_units_and_explicit_override(service, point):
    service.settings.default_units = "imperial"
    service.http.add(
        "/forecast",
        {
            "properties": {
                "periods": [
                    {
                        "startTime": "2026-10-14T00:00:00Z",
                        "endTime": "2026-10-14T12:00:00Z",
                        "temperature": 68,
                        "windSpeed": "5 mph",
                    }
                ]
            }
        },
    )
    arguments = {"location": point, "fields": ["temperature", "windSpeed"]}
    result = await service.call("get_forecast", arguments)
    assert result.status == "complete" and result.units["temperature"] == "degF"
    assert service.http.calls[-1][2]["units"] == "us"
    assert "units" not in arguments

    await service.call("get_forecast", {**arguments, "units": "metric"})
    assert service.http.calls[-1][2]["units"] == "si"


@pytest.mark.parametrize(
    "units,upstream,height_unit",
    [("metric", "metric", "m"), ("imperial", "english", "ft"), ("source", "metric", "m")],
)
async def test_tide_unit_preference_reaches_provider(
    service, coops_station, units, upstream, height_unit
):
    service.settings.default_units = units
    service.http.add(
        "/datagetter", {"predictions": [{"t": "2025-04-01 12:00", "v": "1.2", "type": "H"}]}
    )
    result = await service.call(
        "get_tides_currents", {"location": coops_station, "start_date": "2025-04-01"}
    )
    assert result.status == "complete" and result.units["height"] == height_unit
    assert service.http.calls[-1][2]["units"] == upstream


async def test_bundle_inherits_preference_and_allows_per_call_override(service, coops_station):
    service.settings.default_units = "imperial"
    service.http.add(
        "/datagetter", {"predictions": [{"t": "2025-04-01 12:00", "v": "1.2", "type": "H"}]}
    )
    arguments = {"location": coops_station, "start_date": "2025-04-01"}
    result = await service.call(
        "collect_conditions",
        {
            "requests": [
                {"tool": "get_tides_currents", "arguments": arguments},
                {"tool": "get_tides_currents", "arguments": {**arguments, "units": "metric"}},
            ]
        },
    )
    assert result.status == "complete"
    assert [r.units["height"] for r in result.results] == ["ft", "m"]
    assert [p["units"] for _, url, p in service.http.calls if url.endswith("/datagetter")] == [
        "english",
        "metric",
    ]
    assert "units" not in arguments


async def test_buoy_values_converted_with_default_preference(service, ndbc_station):
    service.settings.default_units = "imperial"
    service.http.add(
        "41009.txt", b"#YY MM DD hh mm WSPD WTMP WVHT\n2026 10 13 12 00 5.0 21.0 1.0\n"
    )
    result = await service.call("get_observations", {"location": ndbc_station})
    assert result.status == "complete"
    assert result.records[0].values == {"WSPD": 9.7192, "WTMP": 69.8, "WVHT": 3.2808}
    assert result.units == {"WSPD": "knots", "WTMP": "degF", "WVHT": "ft"}


@pytest.mark.parametrize(
    "units,upstream", [("metric", "metric"), ("imperial", "standard"), ("source", None)]
)
async def test_ncei_preference_and_source_scaling_mode(service, units, upstream):
    service.settings.default_units = units
    service.http.add("/stations/GHCND:TEST", {"id": "GHCND:TEST", "name": "SYNTHETIC"})
    service.http.add(
        "/data",
        {
            "results": [
                {
                    "date": "2025-04-01T00:00:00",
                    "datatype": "TMAX",
                    "value": 20,
                    "attributes": ",,S,",
                    "station": "GHCND:TEST",
                }
            ]
        },
    )
    result = await service.call(
        "get_observations",
        {"provider": "ncei", "location": {"station_id": "GHCND:TEST"}, "start_date": "2025-04-01"},
    )
    assert result.records
    assert service.http.calls[-1][2].get("units") == upstream
    if units == "source":
        assert "units" not in service.http.calls[-1][2]


async def test_invalid_explicit_units_do_not_fall_back_to_preference(service, point):
    service.settings.default_units = "imperial"
    result = await service.call("get_forecast", {"location": point, "units": "invalid"})
    assert result.status == "unavailable" and "invalid_arguments" in result.reasons[0]
    assert not service.http.calls


@pytest.mark.parametrize("units", ["metric", "imperial", "source"])
async def test_mcp_discovery_reports_configured_units_default(units):
    root = Path(__file__).resolve().parents[1]
    config = StdioServerParameters(
        command=sys.executable,
        args=[str(root / "scripts/run_stdio.py")],
        cwd=str(root.parent),
        env={
            "PYTHONPATH": str(root / "src"),
            "WF_DEFAULT_UNITS": units,
            "WF_NCEI_TOKEN": "",
            "WF_SOLUNAR_PERMISSION_REFERENCE": "",
        },
    )
    async with asyncio.timeout(20):
        async with stdio_client(config) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                schemas = [t.inputSchema for t in tools if "units" in t.inputSchema["properties"]]
                assert len(schemas) == 9
                assert all(s["properties"]["units"]["default"] == units for s in schemas)
                assert all(
                    s["properties"]["units"]["enum"] == ["metric", "imperial", "source"]
                    for s in schemas
                )
                result = await session.call_tool("provider_capabilities", {"provider": "nws"})
                payload = json.loads(result.content[0].text)
                assert f"Configured default units: {units}" in payload["qualifications"][0]
