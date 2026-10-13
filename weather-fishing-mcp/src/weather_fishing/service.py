import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from .adapters.coops import COOPS
from .adapters.fisheries import Fisheries
from .adapters.ncei import NCEI
from .adapters.ndbc import NDBC
from .adapters.nws import NWS
from .adapters.solunar import Solunar
from .catalog import CATALOG, enabled
from .collection import Collector
from .http import ProviderError, ProviderHTTP
from .models import (
    AlertsInput,
    AstronomyInput,
    BundleInput,
    BundleResult,
    CapabilitiesInput,
    DiscoveryInput,
    FishingInput,
    ForecastInput,
    ObservationsInput,
    Query,
    Record,
    Result,
    SolunarInput,
    TidesInput,
)
from .resolution import Resolver
from .resolution_models import (
    CollectionInput,
    ConditionsPackage,
    ResolutionResult,
    ResolveInput,
    StationRequest,
    StationSelection,
)


@dataclass
class Tool:
    name: str
    description: str
    schema: type
    handler: object
    kind: str
    output: type = Result

    def input_schema(self, default_units):
        schema = self.schema.model_json_schema()
        if "units" in schema.get("properties", {}):
            schema["properties"]["units"]["default"] = default_units
        return schema


class Service:
    def __init__(
        self, settings, http=None, *, geography=None, relationships=None, solunar_localities=None
    ):
        self.settings = settings
        self.http = http or ProviderHTTP(settings)
        self.adapters = {
            a.provider: a(self.http) for a in [NWS, COOPS, NCEI, NDBC, Fisheries, Solunar]
        }
        self.resolver = Resolver(self, geography, relationships)
        self.collector = Collector(self, solunar_localities)
        tools = [
            Tool(
                "resolve_location",
                "Resolve actual geography; ambiguous places require clarification. "
                "Global geocoding unconfigured; existing NWS lookup covers US coordinates.",
                ResolveInput,
                self.resolver.resolve,
                "information",
                ResolutionResult,
            ),
            Tool(
                "resolve_station_product",
                "Qualify a CO-OPS station/product using reviewed area/waterbody "
                "relationships, provider catalogue, datum, reference metadata and current bin.",
                StationRequest,
                self.resolver.select,
                "information",
                StationSelection,
            ),
            Tool(
                "collect_resolved_conditions",
                "Build a bounded versioned factual package from a resolved "
                "context and local window; independent weather, marine, tides, sun_moon, solunar.",
                CollectionInput,
                self.collector.collect,
                "information",
                ConditionsPackage,
            ),
            Tool(
                "provider_capabilities",
                "Inspect coverage, supported products, gates and reviewed provider terms.",
                CapabilitiesInput,
                self.capabilities,
                "capabilities",
            ),
            Tool(
                "discover_locations",
                (
                    "Discover provider stations/grid zones or verify an exact solunar "
                    "city. No implicit geocoding."
                ),
                DiscoveryInput,
                self.discover,
                "discovery",
            ),
            Tool(
                "get_forecast",
                "Latest NWS weather forecast by coordinates. Archived forecasts unavailable.",
                ForecastInput,
                lambda q: self.adapters["nws"].forecast(q),
                "forecast",
            ),
            Tool(
                "get_marine_forecast",
                "NWS marine grid variables or verified marine-zone text; source units retained.",
                ForecastInput,
                lambda q: self.adapters["nws"].forecast(q, marine=True),
                "forecast",
            ),
            Tool(
                "get_alerts",
                "Active NWS alerts by covered coordinates or explicit zone; no alert archives.",
                AlertsInput,
                self.adapters["nws"].alerts,
                "information",
            ),
            Tool(
                "get_observations",
                (
                    "NDBC standard met, NCEI CDO history, or recent NWS observations. "
                    "Preserve QC and coverage gaps."
                ),
                ObservationsInput,
                self.observations,
                "observation",
            ),
            Tool(
                "get_tides_currents",
                (
                    "CO-OPS tide/current predictions or water-level/current observations. "
                    "Preserve datum and depth bin."
                ),
                TidesInput,
                self.adapters["coops"].tides,
                "prediction",
            ),
            Tool(
                "get_solunar",
                (
                    "Sole solunar source SolunarForecast.com. One exact city/month, April "
                    "2025 or later; license gate."
                ),
                SolunarInput,
                self.adapters["solunar"].monthly,
                "prediction",
            ),
            Tool(
                "get_astronomy",
                (
                    "Sun/moon fields from one SolunarForecast city/month. Source timezone "
                    "must be verified; license gate."
                ),
                AstronomyInput,
                lambda q: self.adapters["solunar"].monthly(q, astronomy=True),
                "prediction",
            ),
            Tool(
                "get_fishing_info",
                (
                    "NOAA marine species/profile excerpts; not comprehensive freshwater or "
                    "verified regulations."
                ),
                FishingInput,
                self.adapters["fisheries"].fishing,
                "information",
            ),
            Tool(
                "collect_conditions",
                (
                    "Run up to eight independent data-tool requests; retain each "
                    "provider's failures/results."
                ),
                BundleInput,
                self.bundle,
                "information",
                BundleResult,
            ),
        ]
        self.tools = {t.name: t for t in tools}

    async def close(self):
        await self.http.close()

    async def capabilities(self, q):
        names = [q.provider] if q.provider else list(CATALOG)
        return Result(
            status="complete",
            provider=q.provider or "catalog",
            kind="capabilities",
            qualifications=[
                f"Configured default units: {self.settings.default_units}; "
                "explicit tool units override this preference",
                (
                    "Integration plan/review record dated 2026-10-13, not proof of access "
                    "rights or production readiness"
                ),
                (
                    "Unknown limits/retention terms are reported as unknown; local limits "
                    "are not provider entitlements"
                ),
            ],
            records=[
                Record(values={"id": p, **CATALOG[p], "enabled": enabled(p, self.settings)})
                for p in names
            ],
        )

    async def discover(self, q):
        adapter = self.adapters[q.provider]
        if q.provider == "solunar":
            today = q.start_date or datetime.now(UTC).date()
            monthly = SolunarInput(
                **q.model_dump(exclude={"station_type", "dataset", "radius_km"}),
                year=today.year,
                month=today.month,
            )
            return await adapter.monthly(monthly, discovery=True)
        return await adapter.discover(q)

    async def observations(self, q):
        return await self.adapters[q.provider].observations(q)

    async def bundle(self, q):
        results = await asyncio.gather(*[self.call(r.tool, r.arguments) for r in q.requests])
        bundle = BundleResult(status="partial", results=results)
        while len(bundle.model_dump_json().encode()) > 120_000:
            pages = [(i, r) for i, r in enumerate(results) if r.records]
            if not pages:
                return BundleResult(
                    status="unavailable",
                    results=[
                        Result(
                            provider=r.provider,
                            kind=r.kind,
                            reasons=["aggregate_metadata_too_large: narrow requests"],
                        )
                        for r in results
                    ],
                )
            index, result = max(pages, key=lambda pair: len(pair[1].model_dump_json()))
            result.records.pop()
            result.next_offset = int(q.requests[index].arguments.get("offset", 0)) + len(
                result.records
            )
            result.status = "partial" if result.records else "unavailable"
            reason = "Aggregate bundle byte budget reached; continue with next_offset"
            if reason not in result.reasons:
                result.reasons.append(reason)
        statuses = [r.status for r in results]
        return BundleResult(
            status="complete"
            if all(s == "complete" for s in statuses)
            else "unavailable"
            if all(s == "unavailable" for s in statuses)
            else "partial",
            results=results,
        )

    async def call(self, name, arguments):
        tool = self.tools.get(name)
        if tool is None:
            return Result(provider="unknown", kind="information", reasons=["unknown_tool"])
        if name in {"resolve_location", "resolve_station_product", "collect_resolved_conditions"}:
            if name == "collect_resolved_conditions" and "units" not in arguments:
                arguments = {**arguments, "units": self.settings.default_units}
            try:
                q = tool.schema.model_validate(arguments)
                # Collection has finite planning stages plus a parallel retrieval stage.
                deadline = self.settings.tool_timeout * (
                    5 if name == "collect_resolved_conditions" else 1
                )
                async with asyncio.timeout(deadline):
                    result = await tool.handler(q)
                if len(result.model_dump_json().encode()) > 120_000:
                    raise ValueError("Resolution metadata exceeds output byte bound")
                return result
            except (ValidationError, ValueError, ProviderError, TimeoutError) as exc:
                reason = (
                    f"{getattr(exc, 'code', 'invalid_arguments_or_resolution')}: {str(exc)[:500]}"
                )
            except Exception as exc:
                reason = f"resolution_error: unexpected {type(exc).__name__}; no fixture fallback"
            if name == "resolve_location":
                return ResolutionResult(state="unavailable", reasons=[reason])
            if name == "resolve_station_product":
                return StationSelection(
                    product=str(arguments.get("product", "unknown"))[:100], reasons=[reason]
                )
            return ConditionsPackage(reasons=[reason])
        if name == "collect_conditions":
            try:
                q = tool.schema.model_validate(arguments)
            except ValidationError:
                return BundleResult(
                    status="unavailable",
                    results=[
                        Result(
                            provider="unknown",
                            kind="information",
                            reasons=["invalid_arguments: expected 1-8 data-tool requests"],
                        )
                    ],
                )
            return await self.bundle(q)
        # Resolve defaults before validation without mutating the caller's arguments.
        # Bundles route their individual calls here too, so preferences apply there.
        if issubclass(tool.schema, Query) and "units" not in arguments:
            arguments = {**arguments, "units": self.settings.default_units}
        try:
            q = tool.schema.model_validate(arguments)
        except ValidationError as exc:
            return Result(
                provider=str(arguments.get("provider", "unknown")),
                kind=tool.kind,
                reasons=[
                    "invalid_arguments: "
                    + "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                        for e in exc.errors(include_input=False)
                    )[:1000]
                ],
            )
        provider = getattr(q, "provider", None)
        kind = getattr(q, "kind", tool.kind)
        if name == "get_tides_currents":
            kind = (
                "prediction"
                if q.product in {"predictions", "currents_predictions"}
                else "observation"
            )
        if name == "provider_capabilities":
            return await self.capabilities(q)
        supported = {
            "discover_locations": set(self.adapters),
            "get_forecast": {"nws"},
            "get_marine_forecast": {"nws"},
            "get_alerts": {"nws"},
            "get_observations": {"nws", "ncei", "ndbc"},
            "get_tides_currents": {"coops"},
            "get_solunar": {"solunar"},
            "get_astronomy": {"solunar"},
            "get_fishing_info": {"fisheries"},
        }
        result = Result(
            provider=provider,
            kind=kind,
            source_url=CATALOG[provider]["documentation"],
            timezone=q.timezone,
            location=q.location.model_dump(exclude_none=True),
            missing_fields=list(q.fields),
        )
        if provider not in supported[name]:
            result.reasons = [
                "provider_disabled: access/licensing review and adapter implementation required"
                if not CATALOG[provider]["implemented"]
                else "unsupported_product: provider does not support this tool"
            ]
            return result
        try:
            async with asyncio.timeout(self.settings.tool_timeout):
                result = await tool.handler(q)
                # Bound model-visible results independently from upstream byte limits.
                # Drop whole records so no data value is silently altered.
                dropped = False
                while result.records and len(result.model_dump_json().encode()) > 60_000:
                    result.records.pop()
                    dropped = True
                if dropped:
                    result.next_offset = q.offset + len(result.records)
                    result.reasons.append("Output byte budget reached; continue with next_offset")
                    result.status = "partial" if result.records else "unavailable"
                    if not result.records:
                        result.next_offset = None
                        result.reasons.append("Single record too large; request fewer fields")
                return result
        except ProviderError as exc:
            result.reasons = [f"{exc.code}: {exc.message}"]
        except TimeoutError:
            result.reasons = ["tool_timeout: request exceeded bounded execution deadline"]
        except ValueError as exc:
            result.reasons = [f"invalid_request_or_response: {str(exc)[:300]}"]
        except Exception as exc:
            # Do not expose provider bodies, request headers, credentials or tracebacks.
            logging.getLogger(__name__).warning(
                "Adapter failure provider=%s type=%s", provider, type(exc).__name__
            )
            result.reasons = [
                f"adapter_error: unexpected {type(exc).__name__}; no fixture fallback"
            ]
        return result
