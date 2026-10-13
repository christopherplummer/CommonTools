import calendar
import gzip
import io
from datetime import UTC, datetime, timedelta

from lxml import etree

from ..http import ProviderError
from ..models import Record
from ..timeutil import display, finish, instant, relevance
from .base import Adapter

BASE = "https://www.ndbc.noaa.gov"
UNITS = {
    "WDIR": "degrees true",
    "WSPD": "m/s",
    "GST": "m/s",
    "WVHT": "m",
    "DPD": "s",
    "APD": "s",
    "MWD": "degrees true",
    "PRES": "hPa",
    "ATMP": "degC",
    "WTMP": "degC",
    "DEWP": "degC",
    "VIS": "nmi",
    "PTDY": "hPa",
    "TIDE": "ft",
}
MISSING = {
    "WDIR": 999,
    "WSPD": 99,
    "GST": 99,
    "WVHT": 99,
    "DPD": 99,
    "APD": 99,
    "MWD": 999,
    "PRES": 9999,
    "ATMP": 999,
    "WTMP": 999,
    "DEWP": 999,
    "VIS": 99,
    "PTDY": 99,
    "TIDE": 99,
}
ALIASES = {"WD": "WDIR", "BAR": "PRES", "BARO": "PRES"}


def parse_stdmet(text: str, requested: str, units: str) -> tuple[list[Record], dict]:
    lines = text.splitlines()
    header = next(
        (
            line.lstrip("# ").split()
            for line in lines
            if line.lstrip("# ").startswith(("YY ", "YYYY ", "yy "))
        ),
        None,
    )
    if header is None:
        raise ProviderError("invalid_response", "Unrecognized NDBC standard meteorological header")
    minute = "mm" in header
    prefix = 5 if minute else 4
    fields = [ALIASES.get(f, f) for f in header[prefix:]]
    actual_units = {f: UNITS.get(f, "source unspecified") for f in fields}
    rows = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        if len(parts) != len(header):
            raise ProviderError("invalid_response", "NDBC column count changed")
        year = int(parts[0])
        year = year + 1900 if 70 <= year < 100 else year + 2000 if year < 70 else year
        stamp = datetime(
            year, *[int(x) for x in parts[1:4]], int(parts[4]) if minute else 0, tzinfo=UTC
        ).isoformat()
        values = {}
        for f, raw in zip(fields, parts[prefix:], strict=True):
            value = None if raw == "MM" else float(raw)
            if value == MISSING.get(f):
                value = None
            if units == "imperial":
                if f in {"ATMP", "WTMP", "DEWP"}:
                    value = value * 9 / 5 + 32 if value is not None else None
                    actual_units[f] = "degF"
                elif f in {"WSPD", "GST"}:
                    value = value * 1.94384449 if value is not None else None
                    actual_units[f] = "knots"
                elif f == "WVHT":
                    value = value / 0.3048 if value is not None else None
                    actual_units[f] = "ft"
            elif units == "metric":
                if f == "VIS":
                    value = value * 1.852 if value is not None else None
                    actual_units[f] = "km"
                elif f == "TIDE":
                    value = value * 0.3048 if value is not None else None
                    actual_units[f] = "m"
            values[f] = round(value, 4) if value is not None else None
        rows.append(
            Record(
                time=display(stamp, requested),
                source_time=" ".join(parts[:prefix]),
                values=values,
                source_values=dict(zip(fields, parts[prefix:], strict=True)),
                source_units={f: UNITS.get(f, "source unspecified") for f in fields},
                qualifications=[
                    "Source UTC year/month/day/hour/minute tokens normalized to offset ISO"
                ],
            )
        )
    return rows, actual_units


class NDBC(Adapter):
    provider = "ndbc"
    home = BASE + "/faq/dataindex.shtml"
    attribution = "Source: NOAA NDBC (station operator may be a contributing partner)"

    async def station_list(self):
        fetched = await self.http.get(self.provider, BASE + "/activestations.xml")
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(fetched.body, parser=parser)
        return fetched, [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "latitude": float(s.get("lat")),
                "longitude": float(s.get("lon")),
                "operator": s.get("owner"),
                "type": s.get("type"),
                "products": {k: s.get(k) for k in ["met", "currents", "waterquality"]},
            }
            for s in root.findall("station")
        ]

    async def metadata(self, q):
        station = self.station_id(q)
        f, rows = await self.station_list()
        row = next((s for s in rows if s["id"].lower() == station.lower()), None)
        if row is None:
            raise ProviderError(
                "station_metadata_unavailable",
                "Station not in active NDBC catalogue; retired deployment relevance is unverified",
            )
        return f, row

    async def discover(self, q):
        fetched, stations = await self.station_list()
        if q.location.station_id:
            stations = [s for s in stations if s["id"].lower() == q.location.station_id.lower()]
        else:
            self.coordinates(q)
        rows = []
        for s in stations:
            s = relevance(q, s)
            if s.get("distance_km", 0) <= q.radius_km:
                rows.append(Record(values=s))
        rows.sort(key=lambda r: r.values.get("distance_km", 0))
        return finish(
            self.result(
                q,
                "discovery",
                fetched,
                source_timezone="UTC",
                qualifications=[
                    "Active NDBC and partner stations only; not global continuous coverage"
                ],
            ),
            q,
            rows,
        )

    async def observations(self, q):
        metadata, station = await self.metadata(q)
        result = self.result(
            q,
            "observation",
            metadata,
            source_timezone="UTC",
            station=relevance(q, station),
            qualifications=[
                "Station coordinates are catalogue positions, not verified historical deployments",
                "Historical records are observations, not archived marine forecasts",
            ],
        )
        if result.station.get("distance_km", 0) > 100:
            result.reasons.append(
                "Selected representative station is more than 100 km from location"
            )
        ident = station["id"]
        rows = []
        fetched_sources = []
        if not q.historical:
            urls = [BASE + f"/data/realtime2/{ident}.txt"]
            result.qualifications.append(
                "Realtime files generally contain 45 days; automated QC only"
            )
        else:
            q.require_dates(366)
            a, b = q.bounds()
            urls = []
            now = datetime.now(UTC)
            if b.year - a.year > 1:
                raise ValueError("Request at most two calendar years")
            for year in range(
                a.year,
                (b - timedelta(seconds=1)).year + 1,
            ):
                if year < now.year:
                    urls.append(BASE + f"/data/historical/stdmet/{ident.lower()}h{year}.txt.gz")
                elif year == now.year:
                    months = [
                        month
                        for month in range(1, 13)
                        if datetime(
                            year, month, calendar.monthrange(year, month)[1], 23, 59, tzinfo=UTC
                        )
                        >= a
                        and datetime(year, month, 1, tzinfo=UTC) < b
                    ]
                    if len(months) > 3:
                        raise ValueError("Request at most three current-year archive months")
                    for month in months:
                        code = str(month) if month < 10 else {10: "a", 11: "b", 12: "c"}[month]
                        urls.append(
                            BASE + f"/data/stdmet/{calendar.month_abbr[month]}/"
                            f"{ident.lower()}{code}{year}.txt.gz"
                        )
                else:
                    result.reasons.append(f"No historical observations for future year {year}")
            result.qualifications.append(
                "Current-year monthly archives can lag; missing files are reported"
            )
        for url in urls:
            try:
                fetched = await self.http.get(self.provider, url)
                body = fetched.body
                if url.endswith(".gz"):
                    with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream:
                        body = stream.read(self.http.settings.max_response_bytes + 1)
                    if len(body) > self.http.settings.max_response_bytes:
                        raise ProviderError(
                            "response_too_large", "Decompressed archive exceeds limit"
                        )
                parsed, units = parse_stdmet(body.decode("ascii"), q.timezone, q.units)
                for row in parsed:
                    row.source_url = fetched.url
                    row.source_retrieved_at = fetched.retrieved_at
                rows.extend(parsed)
                result.units.update(units)
                fetched_sources.append(fetched)
            except (ProviderError, EOFError, OSError, UnicodeError) as exc:
                result.reasons.append(
                    f"Archive/source unavailable: {url} "
                    f"({getattr(exc, 'code', type(exc).__name__)})"
                )
        if fetched_sources:
            result.source_url = fetched_sources[0].url
            result.source_urls = [metadata.url, *[f.url for f in fetched_sources]]
            result.retrieved_at = min(f.retrieved_at for f in fetched_sources)
            result.cache_hit = all(f.cache_hit for f in fetched_sources)
        else:
            result.retrieved_at = None
        rows.sort(key=lambda r: instant(r.time))
        return finish(result, q, rows)
