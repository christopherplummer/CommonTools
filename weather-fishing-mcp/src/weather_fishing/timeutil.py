import math
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .models import Query, Record, Result


def instant(value: str, zone: str = "UTC") -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed


def display(value: str, requested: str, source: str = "UTC") -> str:
    return instant(value, source).astimezone(ZoneInfo(requested)).isoformat()


def distance_km(lat: float, lon: float, other_lat: float, other_lon: float) -> float:
    a, b = math.radians(lat), math.radians(other_lat)
    d = (
        math.sin((b - a) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(other_lon - lon) / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(d)))


def relevance(q: Query, station: dict) -> dict:
    station = dict(station)
    station["representative"] = True
    station["relevance"] = "Verified provider station; local suitability requires review"
    if q.location.latitude is not None and station.get("latitude") is not None:
        station["distance_km"] = round(
            distance_km(
                q.location.latitude, q.location.longitude, station["latitude"], station["longitude"]
            ),
            3,
        )
        station["relevance"] = "Geographic distance only; no same-waterbody or terrain guarantee"
    return station


def finish(result: Result, q: Query, records: list[Record], *, empty_ok=False) -> Result:
    bounds = q.bounds()
    if bounds:
        filtered = []
        for record in records:
            if record.time:
                begin = instant(record.time).astimezone(UTC)
                end = instant(record.end_time).astimezone(UTC) if record.end_time else begin
                overlaps = end > bounds[0] if record.end_time else begin >= bounds[0]
                if begin < bounds[1] and overlaps:
                    filtered.append(record)
            else:
                filtered.append(record)
        records = filtered
    timed = [r for r in records if r.time]
    if timed:
        if result.valid_from is None:
            result.valid_from = min(timed, key=lambda r: instant(r.time)).time
        if result.valid_to is None:
            result.valid_to = (
                max(timed, key=lambda r: instant(r.end_time or r.time)).end_time
                or max(timed, key=lambda r: instant(r.time)).time
            )
    missing = set(result.missing_fields)
    if q.fields:
        for record in records:
            missing.update(f for f in q.fields if record.values.get(f) is None)
            record.values = {f: record.values.get(f) for f in q.fields}
    else:
        for record in records:
            missing.update(k for k, v in record.values.items() if v is None)
    result.missing_fields = sorted(missing)
    if q.offset + q.limit < len(records):
        result.next_offset = q.offset + q.limit
        result.reasons.append("Response page truncated; continue with next_offset")
    result.records = records[q.offset : q.offset + q.limit]
    if not result.records and (not empty_ok or records):
        result.status = "unavailable"
        result.reasons.append("No matching records available in the requested range/page")
    elif result.reasons or result.missing_fields:
        result.status = "partial"
    else:
        result.status = "complete"
    return result
