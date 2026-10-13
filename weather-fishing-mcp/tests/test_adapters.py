import gzip

import pytest

from weather_fishing.adapters.ndbc import parse_stdmet
from weather_fishing.adapters.solunar import local_event
from weather_fishing.http import ProviderError


async def test_forecast_metadata_dates_units_and_selection(service, point):
    service.http.add(
        "/forecast",
        {
            "properties": {
                "updateTime": "2026-10-13T12:00:00Z",
                "periods": [
                    {
                        "startTime": "2026-10-14T06:00:00-04:00",
                        "endTime": "2026-10-14T18:00:00-04:00",
                        "temperature": 20,
                        "temperatureUnit": "C",
                        "windSpeed": "10 km/h",
                        "name": "SYNTHETIC",
                    }
                ],
            }
        },
    )
    r = await service.call(
        "get_forecast",
        {
            "location": point,
            "units": "metric",
            "timezone": "America/New_York",
            "start_date": "2026-10-14",
            "fields": ["temperature", "windSpeed"],
        },
    )
    assert r.status == "complete"
    assert r.publication_time == "2026-10-13T12:00:00Z"
    assert r.records[0].time.endswith("-04:00")
    assert r.records[0].values == {"temperature": 20, "windSpeed": "10 km/h"}
    assert service.http.calls[-1][2] == {"units": "si"}


async def test_forecast_historical_never_relabels_current(service, point):
    r = await service.call("get_forecast", {"location": point, "kind": "archived_forecast"})
    assert r.status == "unavailable" and r.kind == "archived_forecast"
    assert not service.http.calls


async def test_unsupported_global_nws(service):
    r = await service.call("get_forecast", {"location": {"latitude": 51.5, "longitude": -0.1}})
    assert "unsupported_coverage" in r.reasons[0]
    assert not r.records and r.retrieved_at is None


async def test_marine_grid_intervals_remain_independent(service, point):
    service.http.add(
        "/gridpoints/LWX/1,2",
        {
            "properties": {
                "updateTime": "2026-10-13T00:00:00Z",
                "waveHeight": {
                    "uom": "wmoUnit:m",
                    "values": [{"validTime": "2026-10-14T00:00:00Z/PT2H", "value": 1.2}],
                },
            }
        },
    )
    r = await service.call(
        "get_marine_forecast",
        {"location": point, "fields": ["waveHeight", "wavePeriod"], "units": "source"},
    )
    assert r.status == "partial" and r.missing_fields == ["wavePeriod"]
    assert r.records[0].values["field"] == "waveHeight"
    assert r.records[0].end_time == "2026-10-14T02:00:00+00:00"


async def test_marine_rejects_land_zone(service):
    service.http.add("/zones/forecast/DCZ001", {"properties": {"id": "DCZ001", "type": "land"}})
    r = await service.call("get_marine_forecast", {"location": {"zone_id": "DCZ001"}})
    assert "irrelevant_zone" in r.reasons[0]


async def test_empty_active_alerts_is_valid(service, point):
    service.http.add("/alerts", {"features": []})
    r = await service.call("get_alerts", {"location": point})
    assert r.status == "complete" and not r.records


async def test_coops_datum_source_time_and_dst(service, coops_station):
    service.http.add(
        "/datagetter",
        {
            "predictions": [
                {"t": "2025-11-02 05:30", "v": "1.0", "type": "H"},
                {"t": "2025-11-02 06:30", "v": "0.1", "type": "L"},
            ]
        },
    )
    r = await service.call(
        "get_tides_currents",
        {
            "location": coops_station,
            "start_date": "2025-11-02",
            "timezone": "America/New_York",
            "units": "imperial",
        },
    )
    assert r.status == "complete" and r.datum == "MLLW" and r.source_timezone == "gmt"
    assert r.records[0].time == "2025-11-02T01:30:00-04:00"
    assert r.records[1].time == "2025-11-02T01:30:00-05:00"
    params = service.http.calls[-1][2]
    assert params["begin_date"] == "20251102 04:00"
    assert params["end_date"] == "20251103 04:59" and params["units"] == "english"


async def test_coops_missing_product_explicit(service, coops_station):
    service.http.add("/datagetter", {"error": {"message": "Synthetic unavailable product"}})
    r = await service.call(
        "get_tides_currents", {"location": coops_station, "start_date": "2025-04-01"}
    )
    assert r.status == "unavailable" and "product_unavailable" in r.reasons[0]


async def test_coops_station_and_datum_mismatch(service, coops_station):
    r = await service.call(
        "get_tides_currents",
        {"location": coops_station, "start_date": "2025-04-01", "datum": "NAVD"},
    )
    assert "unsupported_datum" in r.reasons[0]
    assert not any(call[1].endswith("datagetter") for call in service.http.calls)


async def test_currents_require_depth(service, coops_station):
    r = await service.call(
        "get_tides_currents",
        {"location": coops_station, "start_date": "2025-04-01", "product": "currents"},
    )
    assert "bin_required" in r.reasons[0] and r.kind == "observation"


NDBC_TEXT = b"""#YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP DEWP VIS PTDY TIDE
#yr mo dy hr mn degT m/s m/s m sec sec degT hPa degC degC degC nmi hPa ft
2025 04 01 12 00 999 99.0 MM 99.0 8.0 6.0 180 1015.0 20.0 21.0 999.0 99.0 MM MM
"""


def test_ndbc_sentinels_and_imperial_conversion():
    rows, units = parse_stdmet(NDBC_TEXT.decode(), "America/New_York", "imperial")
    assert rows[0].values["WDIR"] is None and rows[0].values["WSPD"] is None
    assert rows[0].values["WTMP"] == 69.8 and units["WTMP"] == "degF"
    assert rows[0].time == "2025-04-01T08:00:00-04:00"


def test_ndbc_old_header_no_minute():
    rows, _ = parse_stdmet("#YY MM DD hh WD BAR\n99 04 01 12 180 1015.0\n", "UTC", "source")
    assert rows[0].time.startswith("1999-") and rows[0].values["PRES"] == 1015


async def test_ndbc_archive_is_observation(service, ndbc_station):
    service.http.add("41009h2025.txt.gz", gzip.compress(NDBC_TEXT))
    r = await service.call(
        "get_observations",
        {
            "location": ndbc_station,
            "historical": True,
            "start_date": "2025-04-01",
            "fields": ["WTMP"],
        },
    )
    assert r.status == "complete" and r.kind == "observation"
    assert r.records[0].values == {"WTMP": 21.0}


async def test_ndbc_missing_archive_no_fixture_substitute(service, ndbc_station):
    r = await service.call(
        "get_observations",
        {"location": ndbc_station, "historical": True, "start_date": "2025-04-01"},
    )
    assert r.status == "unavailable" and r.retrieved_at is None and not r.records


async def test_ncei_preserves_daily_labels_and_pagination(service):
    service.http.add(
        "/stations/GHCND:TEST",
        {
            "id": "GHCND:TEST",
            "name": "SYNTHETIC",
            "latitude": 42.0,
            "longitude": -71.0,
            "mindate": "2000-01-01",
            "maxdate": "2026-01-01",
        },
    )
    service.http.add(
        "/data",
        {
            "metadata": {"resultset": {"count": 2}},
            "results": [
                {
                    "date": "2025-04-01T00:00:00",
                    "datatype": "TMAX",
                    "value": 20,
                    "attributes": ",,S,",
                    "station": "GHCND:TEST",
                }
            ],
        },
    )
    r = await service.call(
        "get_observations",
        {
            "provider": "ncei",
            "location": {"station_id": "GHCND:TEST"},
            "start_date": "2025-04-01",
            "timezone": "Pacific/Auckland",
            "fields": ["TMAX"],
            "limit": 1,
        },
    )
    assert r.status == "partial" and r.next_offset == 1
    assert r.records[0].time is None and r.records[0].source_time == "2025-04-01T00:00:00"
    assert r.records[0].values["attributes"] == ",,S," and r.units["TMAX"] == "degC"
    assert service.http.calls[-1][2]["offset"] == 1


SOLUNAR_ARGS = {
    "location": {"country": "united_states", "state": "california", "city": "beverly_hills"},
    "year": 2025,
    "month": 4,
    "source_timezone": "America/Los_Angeles",
}


async def test_solunar_gate_does_not_fetch(service):
    r = await service.call("get_solunar", SOLUNAR_ARGS)
    assert "license_review_required" in r.reasons[0] and not service.http.calls


async def test_solunar_exact_month_midnight_and_astronomy(service, solunar_page):
    service.settings.solunar_permission_reference = "SYNTHETIC_TEST_PERMISSION_ONLY"
    service.http.add("/4/2025/", solunar_page())
    r = await service.call("get_solunar", {**SOLUNAR_ARGS, "timezone": "UTC"})
    assert r.status == "complete" and len(r.records) == 30
    period = r.records[0].values["major_periods"][0]
    assert period["crosses_midnight"] and period["end"]["time"] == "2025-04-02T08:30:00+00:00"
    assert r.records[0].values["moonrise"]["event"] == "no_event"
    a = await service.call("get_astronomy", {**SOLUNAR_ARGS, "fields": ["sunrise"]})
    assert a.status == "complete" and list(a.records[0].values) == ["sunrise"]


async def test_solunar_reports_date_gaps(service, solunar_page):
    service.settings.solunar_permission_reference = "SYNTHETIC_TEST_PERMISSION_ONLY"
    service.http.add("/4/2025/", solunar_page(days=29))
    r = await service.call("get_solunar", SOLUNAR_ARGS)
    assert r.status == "partial" and "2025-04-30" in r.reasons[0]


@pytest.mark.parametrize(
    "page_args,reason",
    [({"city": "wrong_city"}, "location_mismatch"), ({"month": "October 2026"}, "month_mismatch")],
)
async def test_solunar_rejects_default_page(service, solunar_page, page_args, reason):
    service.settings.solunar_permission_reference = "SYNTHETIC_TEST_PERMISSION_ONLY"
    service.http.add("/4/2025/", solunar_page(**page_args))
    r = await service.call("get_solunar", SOLUNAR_ARGS)
    assert r.status == "unavailable" and reason in r.reasons[0] and not r.records


async def test_solunar_unknown_source_timezone_retains_strings(service, solunar_page):
    service.settings.solunar_permission_reference = "SYNTHETIC_TEST_PERMISSION_ONLY"
    service.http.add("/4/2025/", solunar_page())
    args = {**SOLUNAR_ARGS, "source_timezone": None}
    r = await service.call("get_solunar", args)
    assert r.status == "partial" and "verified_source_timezone" in r.missing_fields
    assert r.records[0].values["sunrise"]["time"] is None


async def test_solunar_highlighted_values_preserved(service, solunar_page):
    service.settings.solunar_permission_reference = "SYNTHETIC_TEST_PERMISSION_ONLY"
    body = solunar_page().replace(b"11:30 PM-1:30 AM", b"<strong>11:30 PM-1:30 AM</strong>")
    body = body.replace(b"Rise: 6:00 AM", b"<strong>Rise: 6:00 AM</strong>")
    body = body.replace(b"SYNTHETIC</p>", b"<strong>SYNTHETIC+</strong></p>")
    service.http.add("/4/2025/", body)
    r = await service.call("get_solunar", SOLUNAR_ARGS)
    assert r.status == "complete"
    assert r.records[0].values["major_periods"]
    assert r.records[0].values["sunrise"]["time"] is not None
    assert r.records[0].values["rating"] == "SYNTHETIC+"


async def test_current_bin_identity_and_max_slack(service, coops_station):
    service.http.add(
        "/stations/8443970/bins.json", {"units": "meters", "bins": [{"num": 1, "depth": 3.5}]}
    )
    service.http.add(
        "/datagetter",
        {
            "current_predictions": {
                "cp": [
                    {
                        "Time": "2025-04-01 12:00",
                        "Velocity_Major": "1.2",
                        "Type": "flood",
                        "Bin": "1",
                    }
                ]
            }
        },
    )
    r = await service.call(
        "get_tides_currents",
        {
            "location": coops_station,
            "product": "currents_predictions",
            "bin": 1,
            "start_date": "2025-04-01",
        },
    )
    assert r.status == "complete" and "vel_type" not in service.http.calls[-1][2]
    assert r.records[0].values["velocity_major"] == 1.2
    assert r.station["bin_metadata"]["catalog_depth"] == 3.5
    invalid = await service.call(
        "get_tides_currents",
        {
            "location": coops_station,
            "product": "currents_predictions",
            "bin": 2,
            "start_date": "2025-04-01",
        },
    )
    assert invalid.status == "unavailable" and "unsupported_bin" in invalid.reasons[0]


async def test_output_byte_budget_pages_whole_records(service, point):
    service.http.add(
        "/alerts",
        {
            "features": [
                {"properties": {"id": str(i), "description": "x" * 20_000}} for i in range(5)
            ]
        },
    )
    r = await service.call("get_alerts", {"location": point, "fields": ["id", "description"]})
    assert r.status == "partial" and r.next_offset == 2 and len(r.records) == 2
    assert len(r.model_dump_json().encode()) < 64_000
    assert r.records[0].values["description"] == "x" * 20_000


async def test_forecast_midnight_end_does_not_overlap_next_day(service, point):
    service.http.add(
        "/forecast",
        {
            "properties": {
                "periods": [
                    {
                        "startTime": "2026-10-13T12:00:00Z",
                        "endTime": "2026-10-14T00:00:00Z",
                        "temperature": 10,
                    },
                    {
                        "startTime": "2026-10-14T00:00:00Z",
                        "endTime": "2026-10-14T12:00:00Z",
                        "temperature": 20,
                    },
                ]
            }
        },
    )
    r = await service.call(
        "get_forecast", {"location": point, "start_date": "2026-10-14", "fields": ["temperature"]}
    )
    assert (
        r.status == "complete" and len(r.records) == 1 and r.records[0].values["temperature"] == 20
    )


async def test_alert_zone_must_cover_supplied_point(service, point):
    service.http.add("/zones/forecast/DCZ001", {"properties": {"id": "DCZ001", "type": "land"}})
    service.http.add("/zones", {"features": []})
    r = await service.call("get_alerts", {"location": {**point, "zone_id": "DCZ001"}})
    assert r.status == "unavailable" and "irrelevant_zone" in r.reasons[0]


async def test_archive_decompressed_byte_limit(service, ndbc_station):
    service.settings.max_response_bytes = 1000
    service.http.add("41009h2025.txt.gz", gzip.compress(b"x" * 1001))
    r = await service.call(
        "get_observations",
        {"location": ndbc_station, "historical": True, "start_date": "2025-04-01"},
    )
    assert r.status == "unavailable" and "response_too_large" in r.reasons[0]


def test_ambiguous_local_sun_time_not_fabricated():
    from datetime import date

    assert local_event("1:30 AM", date(2025, 11, 2), "America/New_York", "UTC")["time"] is None


async def test_fisheries_qualifies_excerpts(service):
    service.http.add(
        "/species/atlantic-cod",
        b"<main><h1>SYNTHETIC Cod</h1>"
        b'<div class="field--name-field-biology">SYNTHETIC marine biology.</div></main>',
    )
    r = await service.call(
        "get_fishing_info",
        {
            "location": {"city": "Boston", "country": "US"},
            "species": "atlantic-cod",
            "topic": "biology",
        },
    )
    assert r.status == "complete" and "SYNTHETIC" in r.records[0].values["text"]
    assert any("freshwater" in s for s in r.qualifications)
    assert any("regulations" in s for s in r.qualifications)


async def test_provider_failure_isolated_in_bundle(service, point, coops_station):
    service.http.add("/forecast", ProviderError("upstream_unavailable", "Synthetic outage"))
    service.http.add(
        "/datagetter", {"predictions": [{"t": "2025-04-01 12:00", "v": "1.2", "type": "H"}]}
    )
    r = await service.call(
        "collect_conditions",
        {
            "requests": [
                {"tool": "get_forecast", "arguments": {"location": point}},
                {
                    "tool": "get_tides_currents",
                    "arguments": {"location": coops_station, "start_date": "2025-04-01"},
                },
            ]
        },
    )
    assert r.status == "partial" and r.results[0].status == "unavailable"
    assert r.results[1].status == "complete" and len(r.results[1].records) == 1


async def test_optional_providers_disabled_and_never_solunar_fallback(service):
    for provider in ["metoffice", "bom", "tides4fishing", "timeanddate"]:
        r = await service.call(
            "get_forecast", {"provider": provider, "location": {"city": "London"}}
        )
        assert "provider_disabled" in r.reasons[0]
    r = await service.call("get_solunar", {**SOLUNAR_ARGS, "provider": "tides4fishing"})
    assert r.provider == "tides4fishing" and r.status == "unavailable" and not service.http.calls


@pytest.mark.parametrize(
    "patch",
    [
        {"timezone": "Invalid/Zone"},
        {"location": {"latitude": 10}},
        {"month": 3},
        {"start_date": "2025-04-30", "end_date": "2025-04-01"},
        {"month": 5, "start_date": "2025-04-01"},
    ],
)
async def test_invalid_requests_rejected_before_io(service, patch):
    r = await service.call("get_solunar", {**SOLUNAR_ARGS, **patch})
    assert (
        r.status == "unavailable" and "invalid_arguments" in r.reasons[0] and not service.http.calls
    )
