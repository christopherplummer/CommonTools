"""Versioned resolution/collection contracts; no provider values are inferred here."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from .models import Input, Provider, Query, Result, UnitSystem


class Point(Input):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Provenance(Input):
    provider: str = Field(max_length=80)
    source_url: str = Field(max_length=1000)
    retrieved_at: str | None = Field(default=None, max_length=80)
    method: str = Field(max_length=300)
    reference: str | None = Field(default=None, max_length=200)


class GeographicCandidate(Input):
    id: str = Field(min_length=1, max_length=200)
    locality: str = Field(min_length=1, max_length=100)
    country: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    point: Point
    precision: str = Field(max_length=100)
    # west, south, east, north; may cross the antimeridian.
    bounds: tuple[float, float, float, float] | None = None
    timezone: str | None = None
    provenance: list[Provenance] = Field(min_length=1, max_length=8)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        return Query.valid_timezone(value) if value else None

    @field_validator("bounds")
    @classmethod
    def valid_bounds(cls, value):
        if value and not (
            -180 <= value[0] <= 180
            and -180 <= value[2] <= 180
            and -90 <= value[1] <= value[3] <= 90
        ):
            raise ValueError("Invalid geographic bounds")
        return value


class ResolveInput(Input):
    place: str | None = Field(default=None, min_length=1, max_length=200)
    coordinates: Point | None = None
    country: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    waterbody: str | None = Field(default=None, max_length=100)
    candidate_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def one_location(self):
        if (self.place is None) == (self.coordinates is None):
            raise ValueError("Supply a place OR coordinates")
        return self


class ResolvedContext(Input):
    locality: GeographicCandidate | None = None
    point: Point
    point_identity: Literal["locality_representative", "submitted_fishing_point"]
    coordinate_precision: str = Field(max_length=100)
    timezone: str | None = None
    waterbody_hint: str | None = Field(default=None, max_length=100)
    provenance: list[Provenance] = Field(max_length=10)
    # Integrity receipt, not an access credential. Re-resolve after a server restart.
    receipt: str = Field(default="", max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        return Query.valid_timezone(value) if value else None


class ResolutionResult(Input):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete", "partial", "unavailable"] = "unavailable"
    state: Literal["resolved", "clarification_required", "dependency_required", "unavailable"]
    context: ResolvedContext | None = None
    candidates: list[GeographicCandidate] = Field(default_factory=list, max_length=10)
    reasons: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


TideProduct = Literal["predictions", "water_level", "hourly_height"]
CurrentProduct = Literal["currents", "currents_predictions"]


class StationRequest(Input):
    context: ResolvedContext
    product: TideProduct | CurrentProduct = "predictions"
    provider: Provider = "coops"
    start_date: date
    end_date: date
    datum: str = Field(default="MLLW", pattern=r"^[A-Z0-9]{2,10}$")
    bin: int | None = Field(default=None, ge=1, le=100)
    station_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{1,80}$")
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def dates(self):
        if not 0 <= (self.end_date - self.start_date).days < 30:
            raise ValueError("Supply an ordered range of at most 30 dates")
        return self


class StationSelection(Input):
    status: Literal["complete", "partial", "unavailable"] = "unavailable"
    relevance_status: Literal["qualified", "unverified", "clarification_required"] = "unverified"
    product: str = Field(max_length=100)
    station: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    next_offset: int | None = None


class LocalWindow(Input):
    local_date: date
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    start_fold: Literal[0, 1] | None = None
    end_fold: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Supply both local clock endpoints")
        if self.end_date and not 0 <= (self.end_date - self.local_date).days < 30:
            raise ValueError("Supply at most 30 ordered local dates")
        for clock in (self.start_time, self.end_time):
            if clock and clock.tzinfo:
                raise ValueError("Local clocks must not carry offsets")
        return self

    def bounds(self, timezone):
        end_day = self.end_date or self.local_date
        if self.start_time is None:
            end_day += timedelta(days=1)
        elif not self.end_date and self.end_time <= self.start_time:
            end_day += timedelta(days=1)
        zone = ZoneInfo(timezone)

        def endpoint(day, clock, fold):
            naive = datetime.combine(day, clock or time())
            candidates = {}
            for f in (0, 1):
                stamp = naive.replace(tzinfo=zone, fold=f)
                if stamp.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive:
                    candidates[stamp.astimezone(UTC)] = stamp
            if not candidates:
                raise ValueError("Nonexistent local time at DST transition")
            if len(candidates) > 1 and fold is None:
                raise ValueError("Ambiguous local time; supply endpoint fold 0 or 1")
            stamp = naive.replace(tzinfo=zone, fold=fold or 0)
            return stamp.astimezone(UTC)

        a = endpoint(self.local_date, self.start_time, self.start_fold)
        b = endpoint(end_day, self.end_time, self.end_fold)
        if b <= a or b - a > timedelta(days=31):
            raise ValueError("Window must be positive and at most 31 elapsed days")
        return a, b


class CollectionInput(Input):
    context: ResolvedContext
    window: LocalWindow
    units: UnitSystem = "metric"
    permitted_providers: list[Provider] = Field(min_length=1, max_length=10)
    tide_product: TideProduct = "predictions"
    datum: str = Field(default="MLLW", pattern=r"^[A-Z0-9]{2,10}$")
    current_product: CurrentProduct | None = None
    current_bin: int | None = Field(default=None, ge=1, le=100)
    # Explicit continuation per category; no hidden pagination loop.
    offsets: dict[str, int] = Field(default_factory=dict, max_length=18)
    limit_per_category: int = Field(default=24, ge=1, le=100)
    max_output_bytes: int = Field(default=60_000, ge=16_000, le=120_000)

    @field_validator("offsets")
    @classmethod
    def valid_offsets(cls, value):
        if any(
            k.split(":")[0] not in {"weather", "marine", "tides", "sun_moon", "solunar", "currents"}
            or (":" in k and (len(k.split(":")) != 2 or k.split(":")[1] not in {"0", "1", "2"}))
            or not 0 <= v <= 1_000_000
            for k, v in value.items()
        ):
            raise ValueError("Invalid category offset")
        return value


class Evidence(Input):
    ref: str
    provider: str
    source_url: str
    retrieved_at: str | None = None
    role: Literal["data", "metadata"]
    tool: str
    arguments: dict[str, Any]


class Category(Input):
    relevance_status: Literal["qualified", "representative", "unverified", "clarification_required"]
    retrieval_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    coverage_status: Literal["unverified", "gaps", "no_records"] = "unverified"
    coverage_gaps: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    selection: StationSelection | None = None
    results: list[Result] = Field(default_factory=list)
    continuations: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class ConditionsPackage(Input):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete", "partial", "unavailable"] = "unavailable"
    context: ResolvedContext | None = None
    window: LocalWindow | None = None
    utc_start: str | None = None
    utc_end: str | None = None
    units_preference: UnitSystem = "metric"
    categories: dict[str, Category] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
