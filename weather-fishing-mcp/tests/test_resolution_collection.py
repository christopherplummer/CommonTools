"""SYNTHETIC geographic/provider fixtures only; no live retrieval claims."""

import copy
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from weather_fishing.http import ProviderError
from weather_fishing.resolution import SolunarLocality, StationRelationship, load_relationships
from weather_fishing.resolution_models import GeographicCandidate, LocalWindow, Point, Provenance


def provenance(method="SYNTHETIC reviewed waterbody relationship"):
    return Provenance(
        provider="fixture",
        source_url="https://fixture.invalid/geography",
        retrieved_at="2026-10-13T12:00:00Z",
        method=method,
    )


def candidate(id="fixture:town", **kwargs):
    return GeographicCandidate(
        id=id,
        locality="SYNTHETIC Springfield",
        country="US",
        region="VA",
        point=Point(latitude=38.9, longitude=-77),
        precision="locality centre",
        bounds=(-77.1, 38.8, -76.9, 39),
        timezone="America/New_York",
        provenance=[provenance()],
        **kwargs,
    )


class SyntheticGeography:
    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    async def search(self, q):
        self.requests.append(q)
        return self.rows

    reverse = search


async def context(service, waterbody="River B", coordinates=None):
    service.resolver.geography = SyntheticGeography([candidate()])
    result = await service.call(
        "resolve_location",
        {
            **({"coordinates": coordinates} if coordinates else {"place": "Springfield"}),
            "waterbody": waterbody,
        },
    )
    assert result.status == "complete"
    return result.context.model_dump(mode="json")


def relationship(station, waterbody, **kwargs):
    return StationRelationship(
        locality_id="fixture:town",
        station_id=station,
        waterbody=waterbody,
        products=[
            "predictions",
            "water_level",
            "hourly_height",
            "currents",
            "currents_predictions",
        ],
        start_date=date(2025, 4, 1),
        end_date=date(2100, 1, 1),
        provenance=provenance(),
        limitation="SYNTHETIC area representative",
        **kwargs,
    )


def stations(service):
    service.resolver.relationships = [relationship("A", "River A"), relationship("B", "River B")]
    rows = [
        {"id": id, "name": "SYNTHETIC " + id, "lat": lat, "lng": -77, "type": "R"}
        for id, lat in [("A", 38.901), ("B", 38.95)]
    ]
    service.http.add("/stations.json", {"stations": rows})
    for row in rows:
        service.http.add(f"/stations/{row['id']}.json", {"stations": [row]})
        service.http.add(f"/stations/{row['id']}/datums.json", {"datums": [{"name": "MLLW"}]})
        service.http.add(f"/stations/{row['id']}/bins.json", {"bins": [{"num": 2, "depth": 10}]})


async def select(service, ctx, **patch):
    return await service.call(
        "resolve_station_product",
        {
            "context": ctx,
            "start_date": "2025-04-01",
            "end_date": "2025-04-02",
            **patch,
        },
    )


def tomorrow():
    return (datetime.now(UTC) + timedelta(days=1)).date().isoformat()


async def collect(service, ctx, **patch):
    return await service.call(
        "collect_resolved_conditions",
        {
            "context": ctx,
            "window": {"local_date": tomorrow()},
            "permitted_providers": ["nws", "coops", "solunar"],
            **patch,
        },
    )


def forecast(service, count=4, padding=""):
    day = tomorrow()
    service.http.add(
        "/forecast/hourly",
        {
            "properties": {
                "periods": [
                    {
                        "startTime": f"{day}T{hour:02}:00:00-04:00",
                        "endTime": f"{day}T{hour + 1:02}:00:00-04:00",
                        "temperature": 20,
                        "temperatureUnit": "C",
                        "windSpeed": "10 km/h" + padding,
                        "probabilityOfPrecipitation": {"value": None},
                        "detailedForecast": padding,
                    }
                    for hour in range(count)
                ]
            }
        },
    )


async def test_ambiguous_place_retains_candidates_and_hints(service):
    geo = SyntheticGeography([candidate(), candidate("fixture:other")])
    service.resolver.geography = geo
    args = {"place": "Springfield", "country": "US", "region": "VA", "waterbody": "River B"}
    r = await service.call("resolve_location", args)
    assert r.state == "clarification_required" and r.context is None and len(r.candidates) == 2
    assert geo.requests[0].region == "VA" and geo.requests[0].waterbody == "River B"
    r = await service.call("resolve_location", {**args, "candidate_id": "fixture:other"})
    assert (
        r.context.locality.id == "fixture:other"
        and r.context.point_identity == "locality_representative"
    )


async def test_submitted_point_is_not_locality_or_station_point(service):
    stations(service)
    service.resolver.relationships[1].area_polygon = [
        Point(latitude=lat, longitude=lon)
        for lat, lon in [(38.8, -77.1), (39, -77.1), (39, -76.9), (38.8, -76.9)]
    ]
    ctx = await context(service, coordinates={"latitude": 38.91, "longitude": -77.01})
    assert ctx["point"] != ctx["locality"]["point"]
    assert ctx["point_identity"] == "submitted_fishing_point"
    r = await select(service, ctx)
    assert r.station["id"] == "B" and r.station["latitude"] != ctx["point"]["latitude"]
    assert ctx["point"] == {"latitude": 38.91, "longitude": -77.01}


async def test_unconfigured_forward_and_failed_reverse_never_guess(service):
    r = await service.call("resolve_location", {"place": "Springfield"})
    assert r.context is None and r.state == "dependency_required" and not service.http.calls
    r = await service.call("resolve_location", {"coordinates": {"latitude": 0, "longitude": 0}})
    assert r.context.point.latitude == 0 and r.context.timezone is None
    assert r.status == "partial" and "timezone" in r.missing_fields
    c = await collect(service, r.context.model_dump(mode="json"))
    assert c.status == "unavailable" and not c.evidence


async def test_existing_nws_coordinate_resolution(service, point):
    body = service.http.responses["/points/38.9000,-77.0000"][1]
    body["properties"]["relativeLocation"] = {
        "geometry": {"coordinates": [-77.02, 38.88]},
        "properties": {"city": "SYNTHETIC city", "state": "VA"},
    }
    r = await service.call("resolve_location", {"coordinates": point})
    assert r.status == "complete" and r.context.timezone == "America/New_York"
    assert r.context.point != r.context.locality.point and r.context.locality.country == "US"


async def test_context_receipt_rejects_model_edits_and_server_restart(service):
    ctx = await context(service)
    patched = copy.deepcopy(ctx)
    patched["point"]["latitude"] = 50
    assert (await collect(service, patched)).status == "unavailable"
    service.resolver.key = b"new process key"
    assert (await collect(service, ctx)).status == "unavailable"
    assert not service.http.calls


async def test_nearby_different_waterbodies_do_not_win_by_distance(service):
    stations(service)
    r = await select(service, await context(service))
    assert r.status == "complete" and r.relevance_status == "qualified" and r.station["id"] == "B"
    assert r.candidates[0]["id"] == "A" and r.candidates[0]["relevance_status"] == "unverified"
    assert any(p.provider == "fixture" for p in r.provenance)
    assert service.http.calls[0][2]["type"] == "tidepredictions"


async def test_unknown_waterbody_clarifies_unless_area_default_reviewed(service):
    stations(service)
    ctx = await context(service, waterbody=None)
    r = await select(service, ctx)
    assert r.relevance_status == "clarification_required" and r.station is None
    service.resolver.relationships[1].default_for_locality = True
    assert (await select(service, ctx)).station["id"] == "B"
    service.resolver.relationships[0].default_for_locality = True
    assert (await select(service, ctx)).relevance_status == "clarification_required"


@pytest.mark.parametrize(
    "patch,reason",
    [
        ({"provider": "ndbc"}, "unsupported_product"),
        ({"datum": "NAVD"}, "unsupported_datum"),
        ({"product": "currents_predictions", "bin": 7}, "unsupported_bin"),
        ({"product": "currents_predictions"}, "unsupported_bin"),
        (
            {"product": "hourly_height", "start_date": "2024-04-01", "end_date": "2024-04-02"},
            "unsupported_dates",
        ),
        (
            {"product": "water_level", "start_date": "2099-04-01", "end_date": "2099-04-02"},
            "unsupported_dates",
        ),
    ],
)
async def test_unsupported_selection_is_explicit(service, patch, reason):
    stations(service)
    r = await select(service, await context(service), **patch)
    assert r.status != "complete" and not any(
        u.endswith("datagetter") for _, u, _ in service.http.calls
    )
    assert reason in str(r.model_dump())


async def test_product_relationship_gate_and_current_bin_are_separate(service):
    stations(service)
    service.resolver.relationships[1].products = ["predictions"]
    ctx = await context(service)
    assert (await select(service, ctx, product="water_level")).station is None
    service.resolver.relationships[1].products.append("currents_predictions")
    r = await select(service, ctx, product="currents_predictions", bin=2)
    assert r.station["bin_metadata"]["depth"] == 10
    assert [p["type"] for _, u, p in service.http.calls if u.endswith("stations.json")][
        -1
    ] == "currentpredictions"


async def test_subordinate_reference_metadata_is_validated(service):
    stations(service)
    row = service.http.responses["/stations/B.json"][1]["stations"][0]
    row.update(type="S", reference_id="REF")
    ctx = await context(service)
    r = await select(service, ctx)
    assert r.status == "unavailable" and r.relevance_status == "qualified"
    service.http.add("/stations/REF.json", {"stations": [{"id": "REF", "type": "R"}]})
    service.http.add(
        "/stations/B/tidepredoffsets.json", {"refStationId": "REF", "heightOffsetHighTide": 1}
    )
    r = await select(service, ctx)
    assert r.status == "complete" and r.station["reference_station"]["id"] == "REF"


@pytest.mark.parametrize("day,hours", [("2025-03-09", 23), ("2025-11-02", 25)])
def test_dst_date_windows(day, hours):
    a, b = LocalWindow(local_date=day).bounds("America/New_York")
    assert (b - a).total_seconds() == hours * 3600


def test_cross_midnight_and_dst_clock_validation():
    a, b = LocalWindow(local_date="2025-04-30", start_time="23:00", end_time="01:00").bounds(
        "America/New_York"
    )
    assert b.day == 1 and (b - a).total_seconds() == 7200
    with pytest.raises(ValueError, match="Ambiguous"):
        LocalWindow(local_date="2025-11-02", start_time="01:30", end_time="02:30").bounds(
            "America/New_York"
        )
    a, b = LocalWindow(
        local_date="2025-11-02", start_time="01:30", end_time="02:30", start_fold=1
    ).bounds("America/New_York")
    assert (b - a).total_seconds() == 3600
    with pytest.raises(ValueError, match="Nonexistent"):
        LocalWindow(local_date="2025-03-09", start_time="02:30", end_time="03:30").bounds(
            "America/New_York"
        )
    with pytest.raises(ValidationError):
        LocalWindow(local_date="2025-01-01", start_time="10:00+04:00", end_time="11:00")


async def test_partial_failure_and_missing_measurement_keep_weather(service, point):
    forecast(service)
    service.http.add(
        "/gridpoints/LWX/1,2", ProviderError("upstream_unavailable", "SYNTHETIC outage")
    )
    stations(service)
    r = await collect(service, await context(service, waterbody=None), limit_per_category=2)
    weather = r.categories["weather"]
    assert "probabilityOfPrecipitation" in weather.results[0].missing_fields
    assert r.status == "partial" and len(weather.results[0].records) == 2
    assert (
        weather.coverage_status == "gaps" and weather.continuations[0]["arguments"]["offset"] == 2
    )
    assert r.categories["marine"].failures[0].startswith("upstream_unavailable")
    assert r.categories["tides"].relevance_status == "clarification_required"
    assert r.categories["solunar"].failures[0].startswith("license_review_required")
    assert not any("not_applicable" in str(c) for c in r.categories.values())
    for row in weather.results[0].records:
        assert row.values["temperature"] == 20 and row.evidence_refs
        ev = next(e for e in r.evidence if e.ref == row.evidence_refs[0])
        assert ev.role == "data" and ev.source_url.endswith("forecast/hourly")


async def test_qualified_relevance_survives_retrieval_failure(service, point):
    stations(service)
    service.http.add("/datagetter", ProviderError("upstream_unavailable", "SYNTHETIC outage"))
    r = await collect(service, await context(service), permitted_providers=["coops"])
    assert r.categories["tides"].relevance_status == "qualified"
    assert r.categories["tides"].retrieval_status == "unavailable"


async def test_aggregate_bound_continuation_does_not_lose_dropped_records(service, point):
    forecast(service, count=20, padding="SYNTHETIC " * 300)
    ctx = await context(service)
    r = await collect(
        service, ctx, permitted_providers=["nws"], limit_per_category=20, max_output_bytes=16000
    )
    assert len(r.model_dump_json().encode()) <= 16000
    c = r.categories["weather"]
    count = len(c.results[0].records)
    assert 0 < count < 20 and c.continuations[0]["arguments"]["offset"] == count
    more = await service.call(c.continuations[0]["tool"], c.continuations[0]["arguments"])
    assert more.records[0].time == f"{tomorrow()}T{count:02}:00:00-04:00"


async def test_clock_window_pagination_uses_original_provider_indices(service, point):
    forecast(service)
    r = await collect(
        service,
        await context(service),
        permitted_providers=["nws"],
        limit_per_category=2,
        window={"local_date": tomorrow(), "start_time": "02:00", "end_time": "04:00"},
    )
    c = r.categories["weather"]
    assert not c.results[0].records and c.continuations[0]["arguments"]["offset"] == 2
    r = await collect(
        service,
        r.context.model_dump(mode="json"),
        permitted_providers=["nws"],
        limit_per_category=2,
        window={"local_date": tomorrow(), "start_time": "02:00", "end_time": "04:00"},
        offsets={"weather:0": 2},
    )
    assert len(r.categories["weather"].results[0].records) == 2


async def test_historical_planning_does_not_fetch_current_forecast(service):
    ctx = await context(service)
    r = await collect(
        service, ctx, permitted_providers=["nws"], window={"local_date": "2025-04-01"}
    )
    assert not service.http.calls and r.categories["weather"].failures == [
        "permitted_provider_missing: historical ncei"
    ]


async def test_solunar_gate_mapping_and_lower_bound_are_preserved(service, solunar_page):
    ctx = await context(service)
    args = {"window": {"local_date": "2025-04-01"}, "permitted_providers": ["solunar"]}
    assert (
        (await collect(service, ctx, **args))
        .categories["solunar"]
        .failures[0]
        .startswith("license_review_required")
    )
    service.settings.solunar_permission_reference = "SYNTHETIC TEST ONLY"
    assert (
        (await collect(service, ctx, **args))
        .categories["solunar"]
        .failures[0]
        .startswith("exact_locality_mapping_required")
    )
    service.collector.solunar_localities = [
        SolunarLocality(
            locality_id="fixture:town",
            country="united_states",
            region="california",
            city="beverly_hills",
            source_timezone="America/Los_Angeles",
            provenance=provenance(),
        )
    ]
    service.http.add("/4/2025/", solunar_page())
    r = await collect(service, ctx, **args)
    assert r.categories["solunar"].results[0].records[0].source_values["source_date"] == "04/01/25"
    assert (
        r.categories["sun_moon"].results[0].records[0].values["sunrise"]["source_time"] == "6:00 AM"
    )
    r = await collect(service, ctx, **{**args, "window": {"local_date": "2025-03-31"}})
    assert r.categories["solunar"].retrieval_status == "unavailable"
    assert "April 2025" in str(r.categories["solunar"].failures)


def test_reviewed_relationship_file_validation_and_bounds(tmp_path):
    path = tmp_path / "SYNTHETIC-relations.json"
    path.write_text("[" + relationship("A", "River A").model_dump_json() + "]")
    assert load_relationships(path)[0].station_id == "A"
    path.write_text("x" * 1_000_001)
    with pytest.raises(ValueError, match="1 MB"):
        load_relationships(path)


async def test_invalid_arguments_do_not_escape_output_bound(service):
    r = await service.call("resolve_station_product", {"product": "SYNTHETIC" * 20000})
    assert r.status == "unavailable" and len(r.model_dump_json().encode()) < 1000


async def test_point_outside_reviewed_polygon_does_not_qualify(service):
    stations(service)
    service.resolver.relationships[1].area_polygon = [
        Point(latitude=lat, longitude=lon)
        for lat, lon in [(38.8, -77.1), (39, -77.1), (39, -76.9), (38.8, -76.9)]
    ]
    ctx = await context(service, coordinates={"latitude": 39.05, "longitude": -77})
    r = await select(service, ctx)
    assert r.station is None and r.relevance_status == "clarification_required"


async def test_upstream_ncei_pagination_and_missing_fields_are_retained(service):
    from pydantic import SecretStr

    service.settings.ncei_token = SecretStr("SYNTHETIC TOKEN")
    service.http.add(
        "/stations",
        {
            "results": [
                {
                    "id": "GHCND:SYNTHETIC",
                    "latitude": 38.91,
                    "longitude": -77,
                    "mindate": "2020-01-01",
                    "maxdate": "2026-01-01",
                }
            ]
        },
    )
    service.http.add(
        "/stations/GHCND:SYNTHETIC",
        {
            "id": "GHCND:SYNTHETIC",
            "latitude": 38.91,
            "longitude": -77,
            "mindate": "2020-01-01",
            "maxdate": "2026-01-01",
        },
    )
    service.http.add(
        "/data",
        {
            "results": [
                {
                    "station": "GHCND:SYNTHETIC",
                    "date": "2025-04-01T00:00:00",
                    "datatype": "TMAX",
                    "value": 21,
                    "attributes": "SYNTHETIC SOURCE",
                }
            ],
            "metadata": {"resultset": {"count": 4}},
        },
    )
    r = await collect(
        service,
        await context(service),
        permitted_providers=["ncei"],
        window={"local_date": "2025-04-01"},
    )
    weather = r.categories["weather"]
    assert weather.relevance_status == "representative" and weather.retrieval_status == "partial"
    result = weather.results[0]
    assert result.missing_fields == ["PRCP", "TMIN"] and result.next_offset == 1
    assert result.records[0].time is None and weather.continuations[0]["arguments"]["offset"] == 1


async def test_cross_month_solunar_success_retained_when_other_month_fails(service, solunar_page):
    service.settings.solunar_permission_reference = "SYNTHETIC TEST ONLY"
    service.collector.solunar_localities = [
        SolunarLocality(
            locality_id="fixture:town",
            country="united_states",
            region="california",
            city="beverly_hills",
            provenance=provenance(),
        )
    ]
    service.http.add("/4/2025/", solunar_page())
    service.http.add("/5/2025/", ProviderError("upstream_unavailable", "SYNTHETIC May outage"))
    r = await collect(
        service,
        await context(service),
        permitted_providers=["solunar"],
        window={"local_date": "2025-04-30", "start_time": "23:00", "end_time": "01:00"},
    )
    for name in ["solunar", "sun_moon"]:
        c = r.categories[name]
        assert c.retrieval_status == "partial" and len(c.results) == 2
        assert c.results[0].records and not c.results[1].records
        assert c.failures == ["upstream_unavailable: SYNTHETIC May outage"]


async def test_legacy_bundle_has_aggregate_bound_and_keeps_pagination(service, point):
    service.http.add(
        "/forecast",
        {
            "properties": {
                "periods": [
                    {
                        "startTime": f"{tomorrow()}T{h:02}:00:00Z",
                        "endTime": f"{tomorrow()}T{h + 1:02}:00:00Z",
                        "detailedForecast": "SYNTHETIC " * 1000,
                    }
                    for h in range(10)
                ]
            }
        },
    )
    r = await service.call(
        "collect_conditions",
        {
            "requests": [
                {
                    "tool": "get_forecast",
                    "arguments": {"location": point, "fields": ["detailedForecast"]},
                }
                for _ in range(8)
            ]
        },
    )
    assert len(r.model_dump_json().encode()) <= 120_000
    assert any("Aggregate bundle" in str(p.reasons) for p in r.results)
    assert all(p.next_offset == len(p.records) for p in r.results)
