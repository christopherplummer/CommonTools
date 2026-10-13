"""Geographic provider port and conservative, evidence-based station qualification."""

import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from pydantic import Field, TypeAdapter, field_validator

from .adapters.coops import META
from .http import ProviderError
from .models import Input, Location, Query
from .resolution_models import (
    GeographicCandidate,
    Point,
    Provenance,
    ResolutionResult,
    ResolvedContext,
    StationSelection,
)

STATION_TYPES = {
    "predictions": "tidepredictions",
    "water_level": "waterlevels",
    "hourly_height": "historicwl",
    "currents": "historiccurrents",
    "currents_predictions": "currentpredictions",
}


class GeographyProvider(Protocol):
    """Configured adapter must use actual geographic data, including point timezone.

    Reverse candidates' timezone MUST apply to the submitted coordinates, rather
    than their locality centre. Forward results must retain ambiguity, not just top rank.
    No adapter is silently enabled for global place search.
    """

    async def search(self, request) -> list[GeographicCandidate]: ...

    async def reverse(self, request) -> list[GeographicCandidate]: ...


class NWSCoordinateGeography:
    """Reuse the existing US points API for submitted coordinates only."""

    def __init__(self, service):
        self.service = service

    async def search(self, request):
        raise ProviderError(
            "geography_provider_unconfigured",
            "Global geocoding/timezone provider remains to be selected and configured",
        )

    async def reverse(self, request):
        q = Query(location=Location(**request.coordinates.model_dump()))
        fetched, props = await self.service.adapters["nws"].points(q)
        relative = props.get("relativeLocation", {})
        p = relative.get("properties", {})
        coords = relative.get("geometry", {}).get("coordinates")
        if not p.get("city") or not coords:
            raise ProviderError(
                "location_unresolved", "NWS point lacks canonical relative locality"
            )
        return [
            GeographicCandidate(
                id=f"nws:{p['city']}:{p.get('state', '')}:{coords[0]}:{coords[1]}",
                locality=p["city"],
                country="US",
                region=p.get("state"),
                point=Point(latitude=coords[1], longitude=coords[0]),
                precision="provider relative-locality representative point; accuracy unspecified",
                timezone=props.get("timeZone"),
                provenance=[
                    Provenance(
                        provider="nws",
                        source_url=fetched.url,
                        retrieved_at=fetched.retrieved_at,
                        method="NWS point timezone; relativeLocation locality",
                    )
                ],
            )
        ]


class StationRelationship(Input):
    """Operator-reviewed area relationship, never accepted from model tool arguments."""

    locality_id: str = Field(max_length=200)
    station_id: str = Field(pattern=r"^[A-Za-z0-9:_-]{1,80}$")
    waterbody: str = Field(min_length=1, max_length=100)
    waterbody_aliases: list[str] = Field(default_factory=list, max_length=20)
    default_for_locality: bool = False
    # Reviewed polygon of representative applicability; no automatic basin inference.
    area_polygon: list[Point] = Field(default_factory=list, max_length=256)
    products: list[str] = Field(min_length=1, max_length=5)
    start_date: date
    end_date: date
    provenance: Provenance
    limitation: str = Field(min_length=1, max_length=300)

    @field_validator("area_polygon")
    @classmethod
    def valid_polygon(cls, value):
        if value and (
            len(value) < 3
            or max(p.longitude for p in value) - min(p.longitude for p in value) >= 180
        ):
            raise ValueError("Use at least three vertices; split antimeridian polygons")
        return value


def contains(polygon, point):
    """Conservative ray casting; polygon edges are not automatically qualified."""
    inside = False
    x, y = point.longitude, point.latitude
    for a, b in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        cross = (x - a.longitude) * (b.latitude - a.latitude) - (y - a.latitude) * (
            b.longitude - a.longitude
        )
        if (
            abs(cross) < 1e-10
            and min(a.longitude, b.longitude) <= x <= max(a.longitude, b.longitude)
            and min(a.latitude, b.latitude) <= y <= max(a.latitude, b.latitude)
        ):
            return False
        if (a.latitude > y) != (b.latitude > y):
            intersection = a.longitude + (y - a.latitude) * (b.longitude - a.longitude) / (
                b.latitude - a.latitude
            )
            if x < intersection:
                inside = not inside
    return inside


def load_relationships(path: Path | None):
    if path is None:
        return []
    with path.open("rb") as stream:
        body = stream.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("Station relationship catalogue exceeds 1 MB")
    rows = TypeAdapter(list[StationRelationship]).validate_json(body)
    if len(rows) > 1000:
        raise ValueError("Station relationship catalogue exceeds 1000 relationships")
    if any(r.end_date < r.start_date or set(r.products) - STATION_TYPES.keys() for r in rows):
        raise ValueError("Invalid relationship dates/products")
    return rows


class SolunarLocality(Input):
    locality_id: str = Field(max_length=200)
    country: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    region: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    city: str = Field(pattern=r"^[a-z0-9_]{1,100}$")
    source_timezone: str | None = None
    provenance: Provenance

    @classmethod
    def load(cls, path):
        if path is None:
            return []
        with path.open("rb") as stream:
            body = stream.read(1_000_001)
        if len(body) > 1_000_000:
            raise ValueError("Solunar locality catalogue exceeds 1 MB")
        return TypeAdapter(list[cls]).validate_json(body)


class Resolver:
    def __init__(self, service, geography=None, relationships=None):
        self.service = service
        self.geography = geography or NWSCoordinateGeography(service)
        self.relationships = (
            relationships
            if relationships is not None
            else load_relationships(service.settings.station_relationships_file)
        )
        self.key = secrets.token_bytes(32)

    def signature(self, context):
        body = context.model_dump_json(exclude={"receipt"}).encode()
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def verify(self, context):
        if not hmac.compare_digest(context.receipt, self.signature(context)):
            raise ValueError("Context receipt invalid/expired; call resolve_location again")

    async def resolve(self, q):
        context = None
        if q.coordinates:
            context = ResolvedContext(
                point=q.coordinates,
                point_identity="submitted_fishing_point",
                coordinate_precision="submitted precision; positional accuracy unverified",
                waterbody_hint=q.waterbody,
                provenance=[
                    Provenance(
                        provider="caller",
                        source_url="urn:submitted-coordinates",
                        method="Preserved supplied coordinates without snapping",
                    )
                ],
            )
        try:
            async with asyncio.timeout(self.service.settings.tool_timeout):
                rows = await (
                    self.geography.reverse(q) if q.coordinates else self.geography.search(q)
                )
            rows = [GeographicCandidate.model_validate(r) for r in rows]
            if len(rows) > 10:
                return ResolutionResult(
                    state="clarification_required",
                    candidates=rows[:10],
                    reasons=["More than ten candidates; refine country/region/place"],
                )
            if q.candidate_id:
                rows = [r for r in rows if r.id == q.candidate_id]
            if len(rows) > 1:
                return ResolutionResult(
                    state="clarification_required",
                    candidates=rows,
                    reasons=["Select a returned candidate_id or refine the place"],
                )
            if not rows:
                raise ProviderError("location_unresolved", "No matching geographic candidate")
            candidate = rows[0]
            if context is None:
                context = ResolvedContext(
                    point=candidate.point,
                    point_identity="locality_representative",
                    coordinate_precision=candidate.precision,
                    provenance=[],
                    waterbody_hint=q.waterbody,
                )
            context.locality = candidate
            context.timezone = candidate.timezone
            context.provenance.extend(candidate.provenance)
            context.receipt = self.signature(context)
            return ResolutionResult(
                status="complete" if context.timezone else "partial",
                state="resolved" if context.timezone else "dependency_required",
                context=context,
                missing_fields=[] if context.timezone else ["timezone"],
            )
        except (ProviderError, TimeoutError, ValueError) as exc:
            if context:
                context.receipt = self.signature(context)
            return ResolutionResult(
                status="partial" if context else "unavailable",
                state="dependency_required",
                context=context,
                reasons=[f"{getattr(exc, 'code', 'resolution_failed')}: {str(exc)[:300]}"],
                missing_fields=["canonical_locality", "timezone"],
            )

    async def select(self, q):
        self.verify(q.context)
        out = StationSelection(product=q.product)
        if q.provider != "coops":
            out.reasons = ["unsupported_product: station/product resolver supports CO-OPS only"]
            return out
        if (
            q.product in {"water_level", "hourly_height", "currents"}
            and q.end_date > datetime.now(UTC).date()
        ):
            out.reasons = ["unsupported_dates: observations cannot cover future dates"]
            return out
        discovery = await self.service.call(
            "discover_locations",
            {
                "provider": "coops",
                "location": q.context.point.model_dump(),
                "station_type": STATION_TYPES[q.product],
                "limit": 20,
                "offset": q.offset,
                "timezone": q.context.timezone or "UTC",
            },
        )
        out.candidates = [r.values for r in discovery.records]
        out.next_offset = discovery.next_offset
        out.provenance = [
            Provenance(
                provider="coops",
                source_url=discovery.source_url,
                retrieved_at=discovery.retrieved_at,
                method=f"Product catalogue: {STATION_TYPES[q.product]}",
            )
        ]
        if discovery.status == "unavailable":
            out.reasons = discovery.reasons
            return out
        locality = q.context.locality
        qualified = []
        for station in out.candidates:
            relationships = [
                r
                for r in self.relationships
                if locality and r.locality_id == locality.id and r.station_id == station["id"]
            ]
            matching = [
                r
                for r in relationships
                if (
                    q.context.waterbody_hint.casefold()
                    in [x.casefold() for x in [r.waterbody, *r.waterbody_aliases]]
                    if q.context.waterbody_hint
                    else r.default_for_locality
                )
            ]
            station["relevance_status"] = "unverified"
            station["waterbodies"] = sorted({r.waterbody for r in relationships})
            for relationship in matching:
                if q.context.point_identity == "submitted_fishing_point" and (
                    not relationship.area_polygon
                    or not contains(relationship.area_polygon, q.context.point)
                ):
                    station["qualification_failure"] = "fishing_point_area_unverified"
                elif q.product not in relationship.products:
                    station["qualification_failure"] = "unsupported_product: reviewed relationship"
                elif q.start_date < relationship.start_date or q.end_date > relationship.end_date:
                    station["qualification_failure"] = "unsupported_dates: reviewed relationship"
                elif q.station_id and station["id"] != q.station_id:
                    continue
                else:
                    station["relevance_status"] = "qualified"
                    qualified.append((station, relationship))
        waterbodies = {r.waterbody for _, r in qualified}
        if not qualified or len(waterbodies) != 1:
            out.relevance_status = "clarification_required"
            out.reasons = [
                "waterbody_or_relationship_required: distance alone cannot qualify tides"
            ]
            out.limitations = ["Candidate page is bounded; omitted candidates may remain"]
            out.status = "partial"
            return out
        # Distance ranks ONLY within an already qualified waterbody/area relationship.
        station, relationship = min(qualified, key=lambda x: x[0].get("distance_km", float("inf")))
        out.relevance_status = "qualified"
        out.station = dict(station)
        out.provenance.append(relationship.provenance)
        out.limitations = [
            relationship.limitation,
            "Representative station; retrieval does not prove complete local coverage",
        ]
        try:
            query = Query(
                location=Location(station_id=station["id"]),
                start_date=q.start_date,
                end_date=q.end_date,
            )
            fetched, meta = await self.service.adapters["coops"].metadata(query)
            out.station.update(
                {
                    "type": meta.get("type"),
                    "reference_id": meta.get("reference_id"),
                    "details": meta.get("details"),
                }
            )
            if q.product in {"water_level", "hourly_height", "currents"}:
                details = meta.get("details", {})
                established, removed = details.get("established"), details.get("removed")
                if (established and str(q.start_date) < established[:10]) or (
                    removed and str(q.end_date) > removed[:10]
                ):
                    raise ProviderError("unsupported_dates", "Outside station installation period")
            out.provenance.append(
                Provenance(
                    provider="coops",
                    source_url=fetched.url,
                    retrieved_at=fetched.retrieved_at,
                    method="Station identity and reference/subordinate metadata",
                )
            )
            current = q.product in {"currents", "currents_predictions"}
            if q.product in {"predictions", "currents_predictions"} and meta.get("type") == "S":
                reference = meta.get("reference_id")
                if not reference:
                    raise ProviderError(
                        "reference_metadata_missing", "Subordinate reference absent"
                    )
                ref_q = Query(location=Location(station_id=reference))
                ref_f, ref_meta = await self.service.adapters["coops"].metadata(ref_q)
                out.station["reference_station"] = {
                    "id": ref_meta["id"],
                    "type": ref_meta.get("type"),
                }
                resource = "currentpredictionoffsets" if current else "tidepredoffsets"
                offsets = await self.service.http.get(
                    "coops", f"{META}/stations/{station['id']}/{resource}.json"
                )
                out.station["prediction_offsets"] = offsets.json()
                if out.station["prediction_offsets"].get("refStationId") != reference:
                    raise ProviderError(
                        "reference_metadata_mismatch", "Prediction offsets reference mismatch"
                    )
                if current:
                    ref_bins = await self.service.http.get(
                        "coops", f"{META}/stations/{reference}/bins.json"
                    )
                    ref_bin = out.station["prediction_offsets"].get("refStationBin")
                    if ref_bin not in [v.get("num") for v in ref_bins.json().get("bins", [])]:
                        raise ProviderError(
                            "unsupported_reference_bin",
                            "Subordinate current reference bin unverified",
                        )
                    out.provenance.append(
                        Provenance(
                            provider="coops",
                            source_url=ref_bins.url,
                            retrieved_at=ref_bins.retrieved_at,
                            method="Subordinate current reference bin",
                        )
                    )
                for f in (ref_f, offsets):
                    out.provenance.append(
                        Provenance(
                            provider="coops",
                            source_url=f.url,
                            retrieved_at=f.retrieved_at,
                            method="Subordinate reference/offset validation",
                        )
                    )
            elif q.product in {"predictions", "currents_predictions"} and not meta.get("type"):
                out.limitations.append("Reference/subordinate type absent in provider metadata")
            resource = "bins" if current else "datums"
            fetched = await self.service.http.get(
                "coops", f"{META}/stations/{station['id']}/{resource}.json", {"units": "metric"}
            )
            body = fetched.json()
            out.provenance.append(
                Provenance(
                    provider="coops",
                    source_url=fetched.url,
                    retrieved_at=fetched.retrieved_at,
                    method="Depth-bin validation" if current else "Datum validation",
                )
            )
            if current:
                bins = body.get("bins", body.get("binList", []))
                selected = next(
                    (b for b in bins if int(b.get("num", b.get("bin", -1))) == q.bin), None
                )
                if selected is None:
                    raise ProviderError(
                        "unsupported_bin", "Explicit bin must appear in provider metadata"
                    )
                out.station["bin_metadata"] = selected
            elif q.datum not in [d.get("name") for d in body.get("datums", [])]:
                raise ProviderError("unsupported_datum", "Datum must appear in provider metadata")
            out.status = "complete"
            if out.next_offset is not None:
                out.limitations.append(
                    "Selection considered one candidate page; not globally nearest"
                )
        except (ProviderError, ValueError) as exc:
            out.reasons.append(f"{getattr(exc, 'code', 'metadata_invalid')}: {str(exc)[:300]}")
        return out
