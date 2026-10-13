from ..http import Fetched, ProviderError, ProviderHTTP
from ..models import Query, Result


class Adapter:
    provider: str
    attribution: str
    home: str

    def __init__(self, http: ProviderHTTP):
        self.http = http

    def result(self, q: Query, kind, fetched: Fetched | None = None, **kwargs) -> Result:
        return (
            Result(
                provider=self.provider,
                kind=kind,
                timezone=q.timezone,
                location=q.location.model_dump(exclude_none=True),
                source_url=self.home,
                attribution=self.attribution,
                **kwargs,
            )
            if fetched is None
            else Result(
                provider=self.provider,
                kind=kind,
                timezone=q.timezone,
                location=q.location.model_dump(exclude_none=True),
                source_url=fetched.url,
                retrieved_at=fetched.retrieved_at,
                cache_hit=fetched.cache_hit,
                attribution=self.attribution,
                **kwargs,
            )
        )

    def coordinates(self, q):
        if q.location.latitude is None:
            raise ProviderError(
                "location_unresolved",
                "Coordinates required. City names are not implicitly geocoded",
            )

    def station_id(self, q):
        if not q.location.station_id:
            raise ProviderError(
                "station_required", "Discover and select a provider station_id first"
            )
        return q.location.station_id
