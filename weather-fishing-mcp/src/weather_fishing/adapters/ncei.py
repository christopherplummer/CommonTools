import math

from ..http import ProviderError
from ..models import Record
from ..timeutil import finish, relevance
from .base import Adapter

BASE = "https://www.ncei.noaa.gov/cdo-web/api/v2"


class NCEI(Adapter):
    provider = "ncei"
    home = "https://www.ncei.noaa.gov/cdo-web/webservices/v2"
    attribution = "Source: NOAA NCEI Climate Data Online; observe dataset-specific source rights"

    async def metadata(self, q):
        station = self.station_id(q)
        fetched = await self.http.get(self.provider, BASE + "/stations/" + station)
        p = fetched.json()
        if p.get("id") != station:
            raise ProviderError("station_mismatch", "NCEI station identity mismatch")
        return fetched, p

    async def discover(self, q):
        if q.location.station_id:
            fetched, p = await self.metadata(q)
            stations = [p]
            count = 1
        else:
            self.coordinates(q)
            lat = q.location.latitude
            lon = q.location.longitude
            delta = q.radius_km / 111.0
            delta_lon = delta / max(0.01, math.cos(math.radians(lat)))
            if lon - delta_lon < -180 or lon + delta_lon > 180:
                raise ProviderError(
                    "unsupported_extent", "Split station searches crossing the antimeridian"
                )
            params = {
                "datasetid": q.dataset,
                "extent": f"{max(-90, lat - delta)},"
                f"{lon - delta_lon},{min(90, lat + delta)},{lon + delta_lon}",
                "limit": q.limit,
                "offset": q.offset + 1,
            }
            if q.start_date:
                params.update(startdate=str(q.start_date), enddate=str(q.end_date))
            fetched = await self.http.get(self.provider, BASE + "/stations", params)
            body = fetched.json()
            stations = body.get("results", [])
            count = body.get("metadata", {}).get("resultset", {}).get("count", len(stations))
        result = self.result(
            q,
            "discovery",
            fetched,
            source_timezone="dataset-defined calendar dates",
            qualifications=[
                "Global station coverage depends on dataset and period of record",
                "NCEI station discovery pages are ordered by provider, not nearest globally",
            ],
        )
        rows = []
        for p in stations:
            station = relevance(
                q,
                {
                    "id": p["id"],
                    "name": p.get("name"),
                    "latitude": p.get("latitude"),
                    "longitude": p.get("longitude"),
                    "min_date": p.get("mindate"),
                    "max_date": p.get("maxdate"),
                    "data_coverage": p.get("datacoverage"),
                },
            )
            if station.get("distance_km", 0) <= q.radius_km:
                rows.append(Record(values=station))
        if count > q.offset + len(stations):
            result.next_offset = q.offset + len(stations)
            result.reasons.append("More provider stations available; continue with next_offset")
        return finish(result, q.model_copy(update={"offset": 0}), rows)

    async def observations(self, q):
        q.require_dates(366 if q.dataset == "GHCND" else 3650)
        metadata, p = await self.metadata(q)
        params = {
            "datasetid": q.dataset,
            "stationid": p["id"],
            "startdate": str(q.start_date),
            "enddate": str(q.end_date),
            "limit": q.limit,
            "offset": q.offset + 1,
        }
        if q.units != "source":
            params["units"] = "metric" if q.units == "metric" else "standard"
        if q.fields:
            params["datatypeid"] = ",".join(q.fields)
        fetched = await self.http.get(self.provider, BASE + "/data", params)
        body = fetched.json()
        data = body.get("results", [])
        result = self.result(
            q,
            "observation",
            fetched,
            source_urls=[metadata.url],
            station=relevance(
                q,
                {
                    "id": p["id"],
                    "name": p.get("name"),
                    "latitude": p.get("latitude"),
                    "longitude": p.get("longitude"),
                    "min_date": p.get("mindate"),
                    "max_date": p.get("maxdate"),
                },
            ),
            source_timezone="dataset-defined calendar dates; not an offset instant",
            qualifications=[
                "Daily/monthly/annual labels are preserved; no midnight UTC is invented",
                "Requested timezone does not relabel source observation days",
                "Attribute strings retain provider measurement/source/quality flags",
                (
                    "Dataset-specific third-party restrictions require review; this is not "
                    "a blanket license"
                ),
            ],
        )
        if result.station.get("distance_km", 0) > 100:
            result.reasons.append(
                "Selected representative station is more than 100 km from location"
            )
        if str(q.start_date) < p.get("mindate", "") or str(q.end_date) > p.get("maxdate", "9999"):
            result.reasons.append(
                "Requested range extends beyond station metadata period of record"
            )
        rows = []
        present = set()
        for r in data:
            if r.get("station") != p["id"]:
                raise ProviderError(
                    "station_mismatch", "NCEI data record belongs to another station"
                )
            datatype = r["datatype"]
            present.add(datatype)
            if q.units == "source":
                unit = "unscaled source integer; consult dataset datatype documentation"
            elif datatype in {"TMAX", "TMIN", "TAVG"}:
                unit = "degC" if q.units == "metric" else "degF"
            elif datatype == "PRCP":
                unit = "mm" if q.units == "metric" else "in"
            else:
                unit = f"provider {params['units']} units; consult dataset datatype documentation"
            result.units[datatype] = unit
            rows.append(
                Record(
                    source_time=r["date"],
                    values={
                        "datatype": datatype,
                        "value": r["value"],
                        "attributes": r.get("attributes"),
                        "source_date": r["date"],
                        "station": r["station"],
                    },
                )
            )
        result.missing_fields = sorted(set(q.fields) - present)
        count = body.get("metadata", {}).get("resultset", {}).get("count", len(data))
        if count > q.offset + len(data):
            result.next_offset = q.offset + len(data)
            result.reasons.append("Upstream page incomplete; continue with next_offset")
        if q.units == "source" or any("consult" in v for v in result.units.values()):
            result.reasons.append("Some datatype units/scales require dataset documentation")
        return finish(result, q.model_copy(update={"fields": [], "offset": 0}), rows)
