"""Deterministic planning, independent retrieval and a bounded factual snapshot."""

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .resolution import SolunarLocality
from .resolution_models import Category, ConditionsPackage, Evidence, StationRequest
from .timeutil import instant

FAILURE_PREFIXES = (
    "unsupported_",
    "provider_",
    "upstream_",
    "credentials_",
    "license_",
    "not_available",
    "product_unavailable",
    "tool_timeout",
    "adapter_error",
    "invalid_",
    "Archive/source unavailable",
)


def reference(*parts):
    return (
        "ev_"
        + hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]
    )


class Collector:
    def __init__(self, service, solunar_localities=None):
        self.service = service
        self.solunar_localities = (
            solunar_localities
            if solunar_localities is not None
            else SolunarLocality.load(service.settings.solunar_localities_file)
        )

    async def collect(self, q):
        out = ConditionsPackage(context=q.context, window=q.window, units_preference=q.units)
        names = ["weather", "marine", "tides", "sun_moon", "solunar"]
        if q.current_product:
            names.append("currents")
        out.categories = {name: Category(relevance_status="unverified") for name in names}
        try:
            self.service.resolver.verify(q.context)
            if not q.context.timezone:
                raise ValueError("Timezone unresolved; configure geographic/timezone provider")
            a, b = q.window.bounds(q.context.timezone)
        except ValueError as exc:
            # An invalid context is not evidence and must not be echoed as resolved geography.
            out.context = None
            out.reasons = [f"context_or_window_invalid: {exc}"]
            for c in out.categories.values():
                c.failures = out.reasons.copy()
            return out
        out.utc_start, out.utc_end = a.isoformat(), b.isoformat()
        zone = ZoneInfo(q.context.timezone)
        first = a.astimezone(zone).date()
        last = (b - timedelta(microseconds=1)).astimezone(zone).date()
        today = datetime.now(zone).date()
        base = {
            "location": q.context.point.model_dump(),
            "timezone": q.context.timezone,
            "units": q.units,
            "start_date": str(first),
            "end_date": str(last),
            "limit": q.limit_per_category,
        }
        plans = {name: [] for name in names}

        async def station_observations(category, provider, start, end):
            c = out.categories[category]
            discovery = await self.service.call(
                "discover_locations",
                {
                    **base,
                    "provider": provider,
                    "start_date": str(start),
                    "end_date": str(end),
                    "limit": 20,
                    "radius_km": 100,
                },
            )
            rows = [r.values for r in discovery.records]
            if provider == "ncei":
                rows = [
                    r
                    for r in rows
                    if r.get("min_date", "9999") <= str(start)
                    and r.get("max_date", "0000") >= str(end)
                ]
            elif provider == "ndbc":
                rows = [r for r in rows if r.get("products", {}).get("met") == "y"]
            if not rows:
                c.failures.extend(
                    discovery.reasons or ["No qualified observation stations on candidate page"]
                )
                return
            station = min(rows, key=lambda r: r.get("distance_km", float("inf")))
            c.relevance_status = "representative"
            c.limitations.append(
                "Station distance is representative only; local coverage unverified"
            )
            if discovery.next_offset is not None:
                c.limitations.append("Discovery considered one page; more stations available")
            plans[category].append(
                (
                    "get_observations",
                    {
                        **base,
                        "provider": provider,
                        "start_date": str(start),
                        "end_date": str(end),
                        "location": {**q.context.point.model_dump(), "station_id": station["id"]},
                        "historical": provider == "ndbc" and start < today,
                        "fields": ["TMAX", "TMIN", "PRCP"]
                        if provider == "ncei"
                        else ["WTMP", "WVHT", "DPD", "WSPD"]
                        if category == "marine"
                        else ["temperature", "windSpeed", "barometricPressure"],
                    },
                )
            )

        for category in ("weather", "marine"):
            if first < today:
                historical = "ncei" if category == "weather" else "ndbc"
                if historical in q.permitted_providers:
                    await station_observations(
                        category, historical, first, min(last, today - timedelta(days=1))
                    )
                else:
                    out.categories[category].failures.append(
                        f"permitted_provider_missing: historical {historical}"
                    )
            if last >= today:
                if "nws" in q.permitted_providers:
                    plans[category].append(
                        (
                            "get_forecast" if category == "weather" else "get_marine_forecast",
                            {
                                **base,
                                "start_date": str(max(first, today)),
                                "hourly": category == "weather",
                                "fields": ["temperature", "windSpeed", "probabilityOfPrecipitation"]
                                if category == "weather"
                                else ["waveHeight", "wavePeriod", "windSpeed"],
                            },
                        )
                    )
                else:
                    out.categories[category].failures.append(
                        "permitted_provider_missing: current/future nws"
                    )

        for category, product in [("tides", q.tide_product), ("currents", q.current_product)]:
            if product is None:
                continue
            c = out.categories[category]
            if "coops" not in q.permitted_providers:
                c.failures = ["permitted_provider_missing: coops"]
                continue
            selection = await self.service.call(
                "resolve_station_product",
                StationRequest(
                    context=q.context,
                    product=product,
                    start_date=first,
                    end_date=last,
                    datum=q.datum,
                    bin=q.current_bin if category == "currents" else None,
                ).model_dump(mode="json"),
            )
            c.selection = selection
            c.relevance_status = selection.relevance_status
            c.limitations.extend(selection.limitations)
            if selection.status != "complete":
                c.failures.extend(selection.reasons)
                continue
            plans[category].append(
                (
                    "get_tides_currents",
                    {
                        **base,
                        "location": {
                            **q.context.point.model_dump(),
                            "station_id": selection.station["id"],
                        },
                        "product": product,
                        "datum": q.datum,
                        **({"bin": q.current_bin} if category == "currents" else {}),
                    },
                )
            )

        locality = q.context.locality
        mapping = next(
            (m for m in self.solunar_localities if locality and m.locality_id == locality.id), None
        )
        months = sorted(
            {
                (first.year, first.month),
                (last.year, last.month),
                ((first + timedelta(days=15)).year, (first + timedelta(days=15)).month),
            }
        )
        months = [
            (y, m)
            for y, m in months
            if (first.year, first.month) <= (y, m) <= (last.year, last.month)
        ]
        for category, tool in [("sun_moon", "get_astronomy"), ("solunar", "get_solunar")]:
            c = out.categories[category]
            if "solunar" not in q.permitted_providers:
                c.failures = [
                    "permitted_provider_missing: sole solunar/astronomy adapter is solunar"
                ]
            elif not self.service.settings.solunar_permission_reference:
                c.failures = ["license_review_required: existing SolunarForecast gate"]
            elif not mapping:
                c.failures = [
                    "exact_locality_mapping_required: configure reviewed SolunarForecast city slugs"
                ]
            else:
                c.relevance_status = "representative"
                c.limitations.append(
                    "Exact provider locality, not point-specific astronomy or fish activity"
                )
                for year, month in months:
                    month_first = date(year, month, 1)
                    month_end = (month_first.replace(day=28) + timedelta(days=4)).replace(
                        day=1
                    ) - timedelta(days=1)
                    plans[category].append(
                        (
                            tool,
                            {
                                **base,
                                "location": {
                                    "country": mapping.country,
                                    "state": mapping.region,
                                    "city": mapping.city,
                                },
                                "year": year,
                                "month": month,
                                "source_timezone": mapping.source_timezone,
                                "start_date": str(max(first, month_first)),
                                "end_date": str(min(last, month_end)),
                            },
                        )
                    )

        # Execute one page per planned request. Adapters retain their own date/unit/access checks.
        requests = []
        for name, calls in plans.items():
            for index, (tool, args) in enumerate(calls):
                key = f"{name}:{index}"
                args["offset"] = q.offsets.get(key, q.offsets.get(name, 0))
                requests.append((name, key, tool, args))
        results = await asyncio.gather(
            *[self.service.call(tool, args) for _, _, tool, args in requests]
        )
        bound_requests = []
        for (name, key, tool, args), result in zip(requests, results, strict=True):
            c = out.categories[name]
            # Filter clock windows WITHOUT moving provider offsets. Interval rows remain intervals.
            filtered = []
            for row in result.records:
                if row.time:
                    start = instant(row.time).astimezone(UTC)
                    end = instant(row.end_time).astimezone(UTC) if row.end_time else start
                    if start >= b or (end <= a if row.end_time else start < a):
                        continue
                    if start > a or end < b:
                        c.limitations.append(
                            "Individual intervals/events do not establish full-window coverage"
                        )
                elif q.window.start_time:
                    c.limitations.append(
                        "Calendar-labelled source rows are not exact clock-window measurements"
                    )
                filtered.append(row)
            # Keep source page indices for safe aggregate byte continuations.
            indices = {id(row): i for i, row in enumerate(result.records)}
            result.records = filtered
            if not filtered and result.status != "unavailable":
                result.status = "unavailable"
                result.reasons.append(
                    "No source records overlap the requested clock window on this page"
                )
            urls = list(
                dict.fromkeys(
                    [
                        u
                        for u in [
                            result.source_url,
                            *result.source_urls,
                            *[r.source_url for r in filtered],
                        ]
                        if u
                    ]
                )
            )
            refs = {}
            for url in urls:
                is_data = bool(filtered) and (
                    url == result.source_url or any(r.source_url == url for r in filtered)
                )
                retrieved_at = next(
                    (
                        r.source_retrieved_at
                        for r in filtered
                        if r.source_url == url and r.source_retrieved_at
                    ),
                    result.retrieved_at if url == result.source_url else None,
                )
                ref = reference(result.provider, url, retrieved_at, tool, args)
                refs[url] = ref
                out.evidence.append(
                    Evidence(
                        ref=ref,
                        provider=result.provider,
                        source_url=url,
                        retrieved_at=retrieved_at,
                        role="data" if is_data else "metadata",
                        tool=tool,
                        arguments=args,
                    )
                )
            for row in filtered:
                source = row.source_url or result.source_url
                row.evidence_refs = [refs[source]] if source in refs else []
            c.results.append(result)
            bound_requests.append((c, result, key, tool, args, indices))
            if result.next_offset is not None:
                c.continuations.append(
                    {
                        "request_key": key,
                        "tool": tool,
                        "arguments": {**args, "offset": result.next_offset},
                    }
                )
            c.failures.extend(r for r in result.reasons if r.startswith(FAILURE_PREFIXES))
            if result.status == "unavailable" and result.retrieved_at is None and not c.failures:
                c.failures.extend(result.reasons)
            c.coverage_gaps.extend(result.reasons)
            if result.missing_fields:
                c.coverage_gaps.append("Missing fields: " + ", ".join(result.missing_fields))
            if name in {"weather", "marine"} and result.records and tool != "get_observations":
                c.relevance_status = (
                    "qualified"  # NWS provider's point/grid mapping, not station proximity.
                )
        # Aggregate bound includes metadata, source raw values and evidence, not just record counts.
        self.statuses(out)
        while len(out.model_dump_json().encode()) > q.max_output_bytes:
            eligible = [r for r in bound_requests if r[1].records]
            if not eligible:
                # Oversized metadata is itself a failure. Never alter a value to fit.
                return ConditionsPackage(
                    status="unavailable",
                    reasons=["aggregate_metadata_too_large: narrow request; output withheld"],
                    units_preference=q.units,
                )
            c, result, key, tool, args, indices = max(
                eligible, key=lambda r: len(r[1].model_dump_json())
            )
            dropped = result.records.pop()
            offset = args["offset"] + indices[id(dropped)]
            result.next_offset = offset
            result.status = "partial" if result.records else "unavailable"
            reason = "Aggregate output byte budget reached; follow continuation"
            if reason not in c.coverage_gaps:
                c.coverage_gaps.append(reason)
            c.continuations = [r for r in c.continuations if r["request_key"] != key]
            c.continuations.append(
                {"request_key": key, "tool": tool, "arguments": {**args, "offset": offset}}
            )
            self.statuses(out)
        return out

    @staticmethod
    def statuses(out):
        for c in out.categories.values():
            has_records = any(r.records for r in c.results)
            c.retrieval_status = (
                "partial"
                if has_records
                and (
                    c.failures or c.continuations or any(r.status != "complete" for r in c.results)
                )
                else "complete"
                if has_records
                else "partial"
                if c.continuations
                else "unavailable"
            )
            c.coverage_status = (
                "gaps"
                if has_records and c.coverage_gaps
                else "unverified"
                if has_records
                else "gaps"
                if c.continuations
                else "no_records"
            )
            c.limitations = list(dict.fromkeys(c.limitations))
            c.coverage_gaps = list(dict.fromkeys(c.coverage_gaps))
        statuses = [c.retrieval_status for c in out.categories.values()]
        out.status = (
            "complete"
            if all(s == "complete" for s in statuses)
            else "unavailable"
            if all(s == "unavailable" for s in statuses)
            else "partial"
        )
