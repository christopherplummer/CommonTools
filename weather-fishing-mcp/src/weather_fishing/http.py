"""Fixed-origin GET transport, bounded bytes, bounded cache and provider quotas."""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import Settings

ORIGINS = {
    "nws": {"api.weather.gov"},
    "coops": {"api.tidesandcurrents.noaa.gov"},
    "ncei": {"www.ncei.noaa.gov"},
    "ndbc": {"www.ndbc.noaa.gov"},
    "fisheries": {"www.fisheries.noaa.gov"},
    "solunar": {"solunarforecast.com", "www.solunarforecast.com"},
}
TTL = {"nws": 300, "coops": 360, "ncei": 3600, "ndbc": 3600, "fisheries": 3600, "solunar": 0}


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class Fetched:
    body: bytes
    url: str
    retrieved_at: str
    headers: dict[str, str]
    cache_hit: bool = False

    def json(self):
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("invalid_response", "Provider did not return valid JSON") from exc


class DailyQuota:
    """Persists CDO attempts across restarts; shared by processes using this database.

    Deploy one worker. Other services sharing the same token must coordinate separately.
    Uses 9000 of the documented 10000 calls/day to leave operational headroom.
    """

    def __init__(self, path: Path):
        self.path = path

    def reserve(self, credential: str, maximum=9000):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fingerprint = hashlib.sha256(credential.encode()).hexdigest()
        day = datetime.now(UTC).date().isoformat()
        with sqlite3.connect(self.path, timeout=3) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS quota (key TEXT, day TEXT, used INTEGER, "
                "PRIMARY KEY(key, day))"
            )
            db.execute("BEGIN IMMEDIATE")
            # The provider's documented daily allowance has no reset timezone.
            # Also counting yesterday conservatively bounds every rolling 24 hours.
            row = db.execute(
                "SELECT COALESCE(SUM(used), 0) FROM quota WHERE key=? AND day>=date(?, '-1 day')",
                (fingerprint, day),
            ).fetchone()
            used = row[0]
            if used >= maximum:
                raise ProviderError("daily_quota", "Local NCEI daily attempt budget exhausted")
            db.execute(
                "INSERT INTO quota VALUES (?, ?, 1) ON CONFLICT(key, day) "
                "DO UPDATE SET used=used+1",
                (fingerprint, day),
            )
            db.execute("DELETE FROM quota WHERE day < date(?, '-2 days')", (day,))


def retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError):
            return 0


class ProviderHTTP:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            timeout=settings.request_timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": settings.user_agent},
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )
        self.cache: OrderedDict[str, tuple[float, Fetched]] = OrderedDict()
        self.locks = {p: asyncio.Lock() for p in ORIGINS}
        self.next_request = dict.fromkeys(ORIGINS, 0.0)
        self.quota = DailyQuota(settings.quota_database)

    async def close(self):
        await self.client.aclose()

    def check_url(self, provider, url):
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.hostname not in ORIGINS.get(provider, set())
            or p.port not in (None, 443)
            or p.username
            or p.password
            or p.fragment
        ):
            raise ProviderError("blocked_url", "Only fixed provider HTTPS origins are allowed")

    def put_cache(self, key, fetched, ttl):
        control = fetched.headers.get("cache-control", "").lower()
        if any(x in control for x in ["no-store", "no-cache", "private"]):
            return
        for directive in control.split(","):
            if directive.strip().startswith("max-age="):
                try:
                    ttl = min(
                        ttl,
                        max(
                            0,
                            int(directive.split("=", 1)[1]) - int(fetched.headers.get("age", "0")),
                        ),
                    )
                except ValueError:
                    ttl = 0
        expires = fetched.headers.get("expires")
        if expires:
            try:
                ttl = min(
                    ttl,
                    max(0, (parsedate_to_datetime(expires) - datetime.now(UTC)).total_seconds()),
                )
            except (ValueError, TypeError):
                ttl = 0
        if ttl <= 0 or len(fetched.body) > self.settings.cache_bytes:
            return
        self.cache[key] = (time.monotonic() + ttl, fetched)
        while (
            len(self.cache) > self.settings.cache_entries
            or sum(len(v[1].body) for v in self.cache.values()) > self.settings.cache_bytes
        ):
            self.cache.popitem(last=False)

    async def get(self, provider: str, url: str, params=None, *, ttl: int | None = None) -> Fetched:
        self.check_url(provider, url)
        request = self.client.build_request("GET", url, params=params)
        key = provider + ":" + str(request.url)
        async with self.locks[provider]:
            now = time.monotonic()
            for old in [k for k, v in self.cache.items() if v[0] <= now]:
                del self.cache[old]
            if key in self.cache:
                self.cache.move_to_end(key)
                f = self.cache[key][1]
                return Fetched(f.body, f.url, f.retrieved_at, f.headers, True)
            headers = {"User-Agent": self.settings.user_agent}
            if provider == "ncei":
                token = self.settings.ncei_token.get_secret_value()
                if not token:
                    raise ProviderError("credentials_missing", "WF_NCEI_TOKEN is required")
                headers["token"] = token
            # NWS requires minute-separated failure retries. Defer these to later calls
            # instead of sleeping for a minute and holding an MCP request open.
            attempts = 1 if provider in {"nws", "solunar"} else 3
            for attempt in range(attempts):
                wait = self.next_request[provider] - time.monotonic()
                if wait > 2:
                    raise ProviderError("provider_cooldown", "Provider cooldown; retry later")
                if wait > 0:
                    await asyncio.sleep(wait)
                if provider == "ncei":
                    await asyncio.to_thread(
                        self.quota.reserve, self.settings.ncei_token.get_secret_value()
                    )
                self.next_request[provider] = time.monotonic() + 1
                try:
                    async with self.client.stream("GET", request.url, headers=headers) as response:
                        if response.status_code in {429, 500, 502, 503, 504}:
                            delay = max(
                                retry_after(response.headers.get("retry-after")),
                                60 if provider == "nws" else 2**attempt,
                            )
                            self.next_request[provider] = time.monotonic() + delay
                            if attempt + 1 == attempts or delay > 2:
                                raise ProviderError(
                                    "rate_limited"
                                    if response.status_code == 429
                                    else "upstream_unavailable",
                                    f"Provider HTTP {response.status_code}",
                                )
                            continue
                        if response.status_code >= 300:
                            # Never follow an untrusted redirect or forward a credential.
                            raise ProviderError(
                                "not_available"
                                if response.status_code == 404
                                else "upstream_http_error",
                                f"Provider HTTP {response.status_code}",
                            )
                        chunks = bytearray()
                        async for chunk in response.aiter_bytes():
                            chunks.extend(chunk)
                            if len(chunks) > self.settings.max_response_bytes:
                                raise ProviderError(
                                    "response_too_large", "Upstream response exceeds limit"
                                )
                        fetched = Fetched(
                            bytes(chunks),
                            str(response.url),
                            datetime.now(UTC).isoformat(),
                            dict(response.headers),
                        )
                        self.put_cache(key, fetched, TTL[provider] if ttl is None else ttl)
                        return fetched
                except httpx.HTTPError as exc:
                    delay = 60 if provider == "nws" else 2**attempt
                    self.next_request[provider] = time.monotonic() + delay
                    if attempt + 1 == attempts or delay > 2:
                        raise ProviderError("network_error", type(exc).__name__) from exc
        raise ProviderError("upstream_unavailable", "Attempts exhausted")
