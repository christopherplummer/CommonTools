from datetime import timedelta

from ..http import ProviderError
from ..models import Record
from ..timeutil import display, finish, instant, relevance
from .base import Adapter

BASE = "https://api.weather.gov"
PERIOD_FIELDS = [
    "name",
    "temperature",
    "temperatureUnit",
    "windSpeed",
    "windDirection",
    "shortForecast",
    "detailedForecast",
    "probabilityOfPrecipitation",
    "relativeHumidity",
    "dewpoint",
    "isDaytime",
]
GRID_FIELDS = [
    "temperature",
    "windSpeed",
    "windDirection",
    "windGust",
    "waveHeight",
    "wavePeriod",
    "waveDirection",
    "probabilityOfPrecipitation",
    "skyCover",
]


class NWS(Adapter):
    provider = "nws"
    home = "https://www.weather.gov/documentation/services-web-api"
    attribution = "Source: US National Weather Service; normalized by CommonTools"

    async def points(self, q):
        self.coordinates(q)
        try:
            fetched = await self.http.get(self.provider, BASE + "/points/" + q.location.point)
        except ProviderError as exc:
            if exc.code == "not_available":
                raise ProviderError(
                    "unsupported_coverage", "NWS has no point coverage here"
                ) from exc
            raise
        return fetched, fetched.json()["properties"]

    async def discover(self, q):
        point, props = await self.points(q)
        fetched = await self.http.get(self.provider, props["observationStations"])
        rows = []
        for f in fetched.json().get("features", []):
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"][:2]
            station = relevance(
                q,
                {
                    "id": p["stationIdentifier"],
                    "name": p["name"],
                    "latitude": lat,
                    "longitude": lon,
                },
            )
            if station.get("distance_km", 0) <= q.radius_km:
                rows.append(Record(values=station))
        rows.sort(key=lambda r: r.values.get("distance_km", float("inf")))
        result = self.result(
            q,
            "discovery",
            fetched,
            source_urls=[point.url],
            source_timezone=props.get("timeZone"),
            qualifications=[
                "Station discovery is limited to NWS point-associated observing stations",
                "Forecast grid/zone relevance is established by the NWS points service",
            ],
        )
        result.location.update(
            {
                k: props.get(k)
                for k in ["gridId", "gridX", "gridY", "forecastZone", "county", "forecastGridData"]
            }
        )
        return finish(result, q, rows)

    async def forecast(self, q, marine=False):
        if q.kind == "archived_forecast":
            raise ProviderError(
                "unsupported_product", "NWS adapter has no archived forecast service"
            )
        if marine and q.location.zone_id:
            return await self.zone_forecast(q)
        point, props = await self.points(q)
        if marine:
            url = props.get("forecastGridData")
        else:
            url = props.get("forecastHourly" if q.hourly else "forecast")
        if not url:
            raise ProviderError("unsupported_product", "Requested forecast not available for point")
        fetched = await self.http.get(
            self.provider,
            url,
            params=None if marine else {"units": "si" if q.units == "metric" else "us"},
        )
        data = fetched.json()["properties"]
        result = self.result(
            q,
            "forecast",
            fetched,
            source_urls=[point.url],
            publication_time=data.get("updateTime") or data.get("updated"),
            valid_from=data.get("validTimes", "/").split("/")[0] or None,
            source_timezone=props.get("timeZone"),
            qualifications=[
                "US NWS point/grid coverage only; no global extrapolation",
                "Latest forecast retrieved now, not a historical forecast archive",
            ],
        )
        result.location.update(
            {k: props.get(k) for k in ["gridId", "gridX", "gridY", "forecastZone"]}
        )
        if not marine:
            rows = [
                Record(
                    time=display(p["startTime"], q.timezone),
                    end_time=display(p["endTime"], q.timezone),
                    source_time=p["startTime"],
                    source_end_time=p["endTime"],
                    values={k: p.get(k) for k in PERIOD_FIELDS},
                )
                for p in data.get("periods", [])
            ]
            result.units = {
                "temperature": "degC" if q.units == "metric" else "degF",
                "windSpeed": "km/h text" if q.units == "metric" else "mph text",
                "dewpoint": "source wmoUnit",
                "relativeHumidity": "percent",
                "probabilityOfPrecipitation": "percent",
            }
        else:
            # Individual grid variables have separate valid intervals: do not invent a
            # joined hourly row or silently fill gaps by interpolating.
            rows = []
            if q.units != "source":
                result.reasons.append("Marine grid variables retain source WMO units")
            for name in q.fields or GRID_FIELDS:
                variable = data.get(name)
                if not isinstance(variable, dict) or not variable.get("values"):
                    result.missing_fields.append(name)
                    continue
                result.units[name] = variable.get("uom", "unspecified")
                for v in variable["values"]:
                    begin, duration = v["validTime"].split("/")
                    # NWS grid durations are ISO 8601 days/hours/minutes.
                    import re

                    m = re.fullmatch(
                        r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", duration
                    )
                    if not m:
                        raise ProviderError(
                            "invalid_response", "Unsupported grid validTime duration"
                        )
                    days, hours, minutes, seconds = [int(x or 0) for x in m.groups()]
                    end = instant(begin) + timedelta(
                        days=days, hours=hours, minutes=minutes, seconds=seconds
                    )
                    rows.append(
                        Record(
                            time=display(begin, q.timezone),
                            end_time=display(end.isoformat(), q.timezone),
                            source_time=v["validTime"],
                            source_units={"value": result.units[name]},
                            values={"field": name, "value": v["value"], "unit": result.units[name]},
                        )
                    )
            result.qualifications.append(
                "Grid coverage verified by NWS; wave-field presence is checked"
            )
            # Field selection has already been applied to grid variables.
            q = q.model_copy(update={"fields": []})
        return finish(result, q, rows)

    async def zone_forecast(self, q):
        zone = q.location.zone_id
        fetched = await self.http.get(self.provider, BASE + "/zones/forecast/" + zone)
        props = fetched.json()["properties"]
        if props.get("id") != zone or props.get("type") not in {"marine", "coastal", "offshore"}:
            raise ProviderError("irrelevant_zone", "Zone is not a verified NWS marine zone")
        if q.location.latitude is not None:
            lookup = await self.http.get(
                self.provider,
                BASE + "/zones",
                {"point": q.location.point, "type": "marine", "include_geometry": "false"},
            )
            if zone not in [f["properties"].get("id") for f in lookup.json().get("features", [])]:
                raise ProviderError(
                    "irrelevant_zone", "Zone does not cover the supplied coordinates"
                )
        if q.start_date:
            raise ProviderError(
                "unsupported_date_filter",
                (
                    "Text zone forecast periods lack absolute validity times; use "
                    "coordinate grid forecasts"
                ),
            )
        forecast = await self.http.get(
            self.provider, BASE + "/zones/forecast/" + zone + "/forecast"
        )
        p = forecast.json()["properties"]
        result = self.result(
            q,
            "forecast",
            forecast,
            source_urls=[fetched.url],
            publication_time=p.get("updated"),
            source_timezone=None,
            units={"detailedForecast": "source text"},
            qualifications=[
                (
                    "Marine zone identity verified; text retains source units and relative "
                    "period names"
                ),
                "No absolute validity times supplied in zone text periods",
                "Zone choice was explicit"
                if q.location.latitude is None
                else "NWS point containment verified",
            ],
        )
        if q.units != "source":
            result.reasons.append("Marine zone text cannot be converted to requested units")
        result.location["zone"] = {"id": zone, "name": props.get("name"), "type": props.get("type")}
        return finish(
            result,
            q,
            [
                Record(
                    values={"name": p.get("name"), "detailedForecast": p.get("detailedForecast")}
                )
                for p in p.get("periods", [])
            ],
        )

    async def alerts(self, q):
        if q.start_date:
            raise ProviderError("unsupported_product", "This tool retrieves active alerts only")
        if q.location.zone_id:
            zone = await self.http.get(
                self.provider, BASE + "/zones/forecast/" + q.location.zone_id
            )
            if zone.json()["properties"].get("id") != q.location.zone_id:
                raise ProviderError("irrelevant_zone", "Zone identity mismatch")
            if q.location.latitude is not None:
                lookup = await self.http.get(
                    self.provider,
                    BASE + "/zones",
                    {"point": q.location.point, "include_geometry": "false"},
                )
                if q.location.zone_id not in [
                    f["properties"].get("id") for f in lookup.json().get("features", [])
                ]:
                    raise ProviderError(
                        "irrelevant_zone", "Zone does not cover supplied coordinates"
                    )
            params = {"zone": q.location.zone_id}
        else:
            await self.points(q)
            params = {"point": q.location.point}
        fetched = await self.http.get(
            self.provider, BASE + "/alerts", {**params, "active": "true"}, ttl=30
        )
        body = fetched.json()
        result = self.result(
            q,
            "information",
            fetched,
            source_timezone="offset timestamps",
            units={"description": "source text"},
            qualifications=["Active alerts only; empty list means no matching active alerts"],
        )
        if body.get("pagination", {}).get("next"):
            result.reasons.append("Upstream alert pagination omitted; narrow the request")
        rows = []
        for f in body.get("features", []):
            p = f["properties"]
            rows.append(
                Record(
                    time=display(p["effective"], q.timezone) if p.get("effective") else None,
                    end_time=display(p["expires"], q.timezone) if p.get("expires") else None,
                    source_time=p.get("sent"),
                    values={
                        k: p.get(k)
                        for k in [
                            "id",
                            "event",
                            "severity",
                            "urgency",
                            "certainty",
                            "headline",
                            "description",
                            "instruction",
                            "areaDesc",
                            "sent",
                        ]
                    },
                )
            )
        return finish(result, q, rows, empty_ok=True)

    async def observations(self, q):
        station = self.station_id(q)
        fetched = await self.http.get(self.provider, BASE + "/stations/" + station)
        p = fetched.json()["properties"]
        if p.get("stationIdentifier") != station:
            raise ProviderError("station_mismatch", "Returned station identity differs")
        lon, lat = fetched.json()["geometry"]["coordinates"][:2]
        params = {"limit": 500}
        if q.bounds():
            a, b = q.bounds()
            params.update(start=a.isoformat(), end=b.isoformat())
        obs = await self.http.get(
            self.provider, BASE + "/stations/" + station + "/observations", params
        )
        result = self.result(
            q,
            "observation",
            obs,
            source_urls=[fetched.url],
            source_timezone="UTC",
            station=relevance(
                q, {"id": station, "name": p.get("name"), "latitude": lat, "longitude": lon}
            ),
            qualifications=[
                "Recent NWS observations; not a guaranteed historical archive",
                "Quantities retain source WMO units and qualityControl flags",
            ],
        )
        if q.units != "source":
            result.reasons.append("Observation quantities retain source units")
        if result.station.get("distance_km", 0) > 100:
            result.reasons.append("Selected station is more than 100 km from the location")
        body = obs.json()
        if body.get("pagination", {}).get("next"):
            result.reasons.append("Upstream observations truncated; narrow the date range")
        rows = []
        for f in body.get("features", []):
            p = f["properties"]
            values = {
                k: p.get(k)
                for k in [
                    "temperature",
                    "dewpoint",
                    "windSpeed",
                    "windDirection",
                    "windGust",
                    "barometricPressure",
                    "seaLevelPressure",
                    "waterTemperature",
                    "relativeHumidity",
                    "textDescription",
                ]
            }
            for k, v in values.items():
                if isinstance(v, dict):
                    result.units[k] = v.get("unitCode", "unspecified")
                    if v.get("value") is None and (not q.fields or k in q.fields):
                        result.missing_fields.append(k)
            rows.append(
                Record(
                    time=display(p["timestamp"], q.timezone),
                    source_time=p["timestamp"],
                    values=values,
                )
            )
        return finish(result, q, rows)
