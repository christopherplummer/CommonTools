from datetime import timedelta

from ..http import ProviderError
from ..models import Record
from ..timeutil import display, finish, relevance
from .base import Adapter

META = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi"
DATA = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def stations(body):
    return body.get("stations", body.get("stationList", []))


def station_info(p):
    return {
        "id": p["id"],
        "name": p.get("name"),
        "latitude": p.get("lat"),
        "longitude": p.get("lng"),
        "state": p.get("state"),
        "tidal": p.get("tidal"),
        "source_standard_timezone": p.get("timezone"),
        "observes_dst": p.get("observedst"),
        "type": p.get("type"),
        "reference_id": p.get("reference_id"),
        "details": p.get("details"),
    }


class COOPS(Adapter):
    provider = "coops"
    home = "https://api.tidesandcurrents.noaa.gov/api/prod/"
    attribution = "Source: NOAA CO-OPS Tides & Currents; normalized by CommonTools"

    async def metadata(self, q):
        station = self.station_id(q)
        f = await self.http.get(
            self.provider, f"{META}/stations/{station}.json", {"expand": "details"}
        )
        rows = stations(f.json())
        if len(rows) != 1 or rows[0].get("id") != station:
            raise ProviderError("station_mismatch", "Station metadata missing or mismatched")
        return f, rows[0]

    async def discover(self, q):
        if q.location.station_id:
            fetched, p = await self.metadata(q)
            rows = [Record(values=relevance(q, station_info(p)))]
        else:
            self.coordinates(q)
            fetched = await self.http.get(
                self.provider, f"{META}/stations.json", {"type": q.station_type}
            )
            rows = []
            for p in stations(fetched.json()):
                station = relevance(q, station_info(p))
                if station.get("distance_km", float("inf")) <= q.radius_km:
                    rows.append(Record(values=station))
            rows.sort(key=lambda r: r.values["distance_km"])
        result = self.result(
            q,
            "discovery",
            fetched,
            source_timezone="station metadata",
            qualifications=[
                "CO-OPS station network only, not global tide coverage",
                "Nearest distance does not verify same estuary, waterbody or current regime",
            ],
        )
        return finish(result, q, rows)

    async def tides(self, q):
        q.require_dates(30)
        metadata, p = await self.metadata(q)
        is_current = q.product in {"currents", "currents_predictions"}
        kind = (
            "prediction" if q.product in {"predictions", "currents_predictions"} else "observation"
        )
        if is_current and q.bin is None:
            raise ProviderError(
                "bin_required", "Explicit depth bin is required for current products"
            )
        params = {
            "station": p["id"],
            "product": q.product,
            "time_zone": "gmt",
            "units": "metric" if q.units in {"metric", "source"} else "english",
            "format": "json",
            "application": "CommonTools_WeatherFishing",
        }
        metadata_urls = [metadata.url]
        bin_metadata = None
        if is_current:
            params["bin"] = q.bin
            params["vel_type"] = "speed_dir" if q.product == "currents_predictions" else "default"
            if q.product == "currents":
                params.pop("vel_type")
            bins = await self.http.get(
                self.provider, f"{META}/stations/{p['id']}/bins.json", {"units": "metric"}
            )
            metadata_urls.append(bins.url)
            bin_body = bins.json()
            available = bin_body.get("bins", bin_body.get("binList", []))
            if q.bin not in [
                int(b.get("num", b.get("bin", b.get("binNumber", -1)))) for b in available
            ]:
                raise ProviderError(
                    "unsupported_bin", "Requested bin is not listed for this station"
                )
            selected = next(
                (
                    b
                    for b in available
                    if int(b.get("num", b.get("bin", b.get("binNumber", -1)))) == q.bin
                ),
                None,
            )
            if selected:
                bin_metadata = {
                    "bin": q.bin,
                    "catalog_depth": selected.get("depth"),
                    "catalog_depth_units": bin_body.get("units"),
                    "qualification": (
                        "Catalogue depth; deployment-specific observation depth unverified"
                    ),
                }
            # Deployment depth may change over time; retain source bin/depth on records.
        else:
            params["datum"] = q.datum
            datums = await self.http.get(
                self.provider, f"{META}/stations/{p['id']}/datums.json", {"units": params["units"]}
            )
            metadata_urls.append(datums.url)
            names = [d.get("name") for d in datums.json().get("datums", [])]
            if q.datum not in names:
                raise ProviderError("unsupported_datum", "Requested datum not listed for station")
        if q.product == "predictions":
            params["interval"] = q.interval or "hilo"
            if params["interval"] == "MAX_SLACK":
                raise ValueError("MAX_SLACK applies to currents only")
        elif q.product == "currents_predictions":
            params["interval"] = q.interval or "MAX_SLACK"
            if params["interval"] == "MAX_SLACK":
                params.pop("vel_type", None)
            if params["interval"] == "hilo":
                raise ValueError("Unsupported current prediction interval")
        elif q.interval is not None:
            raise ValueError("Observed products use their documented default interval")
        a, b = q.bounds()
        params.update(
            begin_date=a.strftime("%Y%m%d %H:%M"),
            end_date=(b - timedelta(minutes=1)).strftime("%Y%m%d %H:%M"),
        )
        fetched = await self.http.get(self.provider, DATA, params)
        body = fetched.json()
        if "error" in body:
            raise ProviderError(
                "product_unavailable", str(body["error"].get("message", "CO-OPS error"))[:300]
            )
        result = self.result(
            q,
            kind,
            fetched,
            source_urls=metadata_urls,
            source_timezone="gmt",
            station=relevance(q, station_info(p)),
            datum=None if is_current else q.datum,
            valid_from=a.isoformat(),
            valid_to=b.isoformat(),
            qualifications=[
                "Retrieved using source time_zone=gmt; output converted to requested IANA timezone",
                "Past-dated predictions are calculations retrieved now, not archived forecasts",
                "Station relevance is geographic only; tide heights retain the selected datum",
            ],
        )
        if result.station.get("distance_km", 0) > 100:
            result.reasons.append(
                "Selected representative station is more than 100 km from location"
            )
        if bin_metadata:
            result.station["bin_metadata"] = bin_metadata
        result.units = (
            {
                "speed": "cm/s" if params["units"] == "metric" else "knots",
                "direction": "degrees",
                "velocity_major": "cm/s" if params["units"] == "metric" else "knots",
                "depth": "source",
            }
            if is_current
            else {"height": "m" if params["units"] == "metric" else "ft"}
        )
        if is_current:
            result.qualifications.append(
                "Bin depths can vary by historical deployment; no depth interpolation"
            )
        values = body.get("predictions", body.get("data"))
        if values is None:
            values = body.get("current_predictions", {}).get("cp", [])
        rows = []
        for row in values:
            source = row.get("t", row.get("Time"))
            if not source:
                raise ProviderError("invalid_response", "CO-OPS record lacks time")

            def number(value):
                if value in [None, ""]:
                    return None
                try:
                    return float(value)
                except ValueError:
                    return value

            normalized = (
                {
                    "speed": number(row.get("s", row.get("Speed"))),
                    "direction": number(row.get("d", row.get("Direction"))),
                    "velocity_major": number(row.get("Velocity_Major")),
                    "bin": row.get("b", row.get("Bin", q.bin)),
                    "depth": row.get("Depth"),
                    "type": row.get("Type"),
                    "source_flags": row.get("f"),
                }
                if is_current
                else {
                    "height": number(row.get("v")),
                    "type": row.get("type"),
                    "sigma": number(row.get("s")),
                    "quality": row.get("q"),
                    "source_flags": row.get("f"),
                }
            )
            # Optional product-specific fields are not all mandatory measurements.
            required = (
                ["velocity_major"]
                if params.get("interval") == "MAX_SLACK"
                else ["speed", "direction"]
                if is_current
                else ["height"]
            )
            normalized = {k: v for k, v in normalized.items() if v is not None or k in required}
            qualifications = []
            if row.get("q") == "p":
                qualifications.append("Preliminary observation")
            rows.append(
                Record(
                    time=display(source, q.timezone),
                    source_time=source,
                    source_values=dict(row),
                    source_units=dict(result.units),
                    values=normalized,
                    qualifications=qualifications,
                )
            )
        return finish(result, q, rows)
