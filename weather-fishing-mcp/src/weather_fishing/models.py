from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Provider = Literal[
    "nws",
    "coops",
    "ncei",
    "ndbc",
    "fisheries",
    "solunar",
    "metoffice",
    "bom",
    "tides4fishing",
    "timeanddate",
]
Kind = Literal[
    "observation",
    "forecast",
    "archived_forecast",
    "prediction",
    "information",
    "discovery",
    "capabilities",
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Location(Input):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    country: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=100)
    station_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{1,80}$")
    zone_id: str | None = Field(default=None, pattern=r"^[A-Z]{2}[CZ][0-9]{3}$")

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Supply both latitude and longitude")
        if not any([self.latitude is not None, self.station_id, self.zone_id, self.city]):
            raise ValueError("Supply coordinates, station_id, zone_id, or country/state/city")
        return self

    @property
    def point(self) -> str:
        if self.latitude is None:
            raise ValueError("Coordinates required; city names are not implicitly geocoded")
        return f"{self.latitude:.4f},{self.longitude:.4f}"


class Query(Input):
    location: Location
    timezone: str = Field(default="UTC", description="Requested output IANA timezone")
    units: Literal["metric", "imperial", "source"] = "metric"
    start_date: date | None = Field(
        default=None, description="Inclusive date in requested timezone"
    )
    end_date: date | None = Field(default=None, description="Inclusive date in requested timezone")
    fields: list[Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]] = Field(
        default_factory=list, max_length=20
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def date_range(self):
        if self.end_date and not self.start_date:
            raise ValueError("end_date requires start_date")
        if self.start_date and not self.end_date:
            self.end_date = self.start_date
        if self.start_date and self.end_date < self.start_date:
            raise ValueError("end_date precedes start_date")
        return self

    def require_dates(self, max_days: int):
        if not self.start_date:
            raise ValueError("start_date and end_date are required")
        if (self.end_date - self.start_date).days + 1 > max_days:
            raise ValueError(f"Request at most {max_days} days at a time")

    def bounds(self) -> tuple[datetime, datetime] | None:
        if self.start_date is None:
            return None
        zone = ZoneInfo(self.timezone)
        return (
            datetime.combine(self.start_date, time(), zone).astimezone(UTC),
            datetime.combine(self.end_date + timedelta(days=1), time(), zone).astimezone(UTC),
        )


class CapabilitiesInput(Input):
    provider: Provider | None = None


class DiscoveryInput(Query):
    provider: Provider
    station_type: Literal[
        "tidepredictions",
        "waterlevels",
        "historicwl",
        "currents",
        "historiccurrents",
        "currentpredictions",
    ] = "tidepredictions"
    dataset: Literal["GHCND", "GSOM", "GSOY"] = "GHCND"
    radius_km: float = Field(default=100, gt=0, le=500)


class ForecastInput(Query):
    provider: Provider = "nws"
    kind: Literal["forecast", "archived_forecast"] = "forecast"
    hourly: bool = False


class AlertsInput(Query):
    provider: Provider = "nws"


class ObservationsInput(Query):
    provider: Provider = "ndbc"
    historical: bool = False
    dataset: Literal["GHCND", "GSOM", "GSOY"] = "GHCND"


class TidesInput(Query):
    provider: Provider = "coops"
    product: Literal[
        "predictions", "water_level", "hourly_height", "currents", "currents_predictions"
    ] = "predictions"
    datum: str = Field(default="MLLW", pattern=r"^[A-Z0-9]{2,10}$")
    interval: Literal["hilo", "h", "6", "10", "30", "60", "MAX_SLACK"] | None = None
    bin: int | None = Field(default=None, ge=1, le=100)


class SolunarInput(Query):
    provider: Provider = "solunar"
    year: int = Field(ge=2025, le=2100)
    month: int = Field(ge=1, le=12)
    source_timezone: str | None = Field(
        default=None,
        description="Operator-verified IANA timezone of selected source city; never inferred",
    )

    @field_validator("source_timezone")
    @classmethod
    def valid_source_timezone(cls, value):
        return Query.valid_timezone(value) if value else None

    @model_validator(mode="after")
    def one_month(self):
        if date(self.year, self.month, 1) < date(2025, 4, 1):
            raise ValueError("Required supported lower bound is April 2025")
        if self.start_date and any(
            (d.year, d.month) != (self.year, self.month) for d in (self.start_date, self.end_date)
        ):
            raise ValueError("Retrieve one country/state/city monthly table at a time")
        return self


class AstronomyInput(SolunarInput):
    pass


class FishingInput(Query):
    provider: Provider = "fisheries"
    species: str = Field(
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=100,
        description="Official NOAA Fisheries species page slug",
    )
    topic: Literal["species", "biology", "habitat", "management", "harvest"] = "species"


class Record(BaseModel):
    time: str | None = Field(default=None, description="Offset ISO instant if source defines one")
    end_time: str | None = None
    source_time: str | None = None
    values: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific fields; see tool reference for keys and units",
    )
    qualifications: list[str] = Field(default_factory=list)


class Result(BaseModel):
    status: Literal["complete", "partial", "unavailable"] = "unavailable"
    provider: str
    kind: Kind
    source_url: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    retrieved_at: str | None = Field(default=None, description="Actual upstream retrieval time")
    served_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    publication_time: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    location: dict[str, Any] = Field(default_factory=dict)
    station: dict[str, Any] | None = None
    timezone: str = "UTC"
    source_timezone: str | None = None
    units: dict[str, str] = Field(default_factory=dict)
    datum: str | None = None
    reasons: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    records: list[Record] = Field(default_factory=list)
    next_offset: int | None = None
    cache_hit: bool = False
    attribution: str | None = None


DataTool = Literal[
    "get_forecast",
    "get_marine_forecast",
    "get_alerts",
    "get_observations",
    "get_tides_currents",
    "get_astronomy",
    "get_solunar",
    "get_fishing_info",
]


class BundleCall(Input):
    tool: DataTool
    arguments: dict[str, Any]


class BundleInput(Input):
    requests: list[BundleCall] = Field(min_length=1, max_length=8)


class BundleResult(BaseModel):
    status: Literal["complete", "partial", "unavailable"]
    results: list[Result]
