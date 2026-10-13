"""HTTPX transport with address validation at the actual TCP connection boundary.

httpcore retains the original hostname for TLS SNI/certificate checks; only the
network backend sees the pinned IP. No second DNS lookup or proxy is involved.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urljoin

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from web_tools.common.errors import ToolError
from web_tools.security.network_policy import NetworkPolicy


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, policy: NetworkPolicy):
        self.policy = policy
        self.backend = AutoBackend()

    async def connect_tcp(
        self,
        host,
        port,
        timeout=None,  # noqa: ASYNC109 - required backend contract
        local_address=None,
        socket_options=None,  # noqa: ASYNC109
    ):
        # Test exceptions are exact origins; validate_url runs on every HTTP request.
        test_exception = any(
            self.policy.validate_url(origin)[:2] == (host, port)
            for origin in self.policy.test_origins
        )
        addresses = await self.policy.resolve(host, port, test_exception=test_exception)
        last_error = None
        for address in addresses:
            try:
                return await self.backend.connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error or httpcore.ConnectError("No destination addresses")

    async def connect_unix_socket(self, *args, **kwargs):
        raise ToolError("blocked_socket", "Unix sockets are not allowed")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


class CoreStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async with map_errors():
            async for chunk in self.stream:
                yield chunk

    async def aclose(self):
        await self.stream.aclose()


@asynccontextmanager
async def map_errors():
    try:
        yield
    except httpcore.TimeoutException as exc:
        raise httpx.TimeoutException(str(exc)) from exc
    except httpcore.NetworkError as exc:
        raise httpx.NetworkError(str(exc)) from exc
    except httpcore.ProtocolError as exc:
        raise httpx.ProtocolError(str(exc)) from exc


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, policy: NetworkPolicy):
        self.policy = policy
        self.pool = httpcore.AsyncConnectionPool(
            network_backend=PinnedBackend(policy),
            max_connections=20,
            max_keepalive_connections=10,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.policy.validate_url(str(request.url))
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        async with map_errors():
            response = await self.pool.handle_async_request(core_request)
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=CoreStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


class NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


class SafeHTTPClient:
    def __init__(
        self,
        policy: NetworkPolicy,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.policy = policy
        self.client = httpx.AsyncClient(
            transport=transport or PinnedTransport(policy),
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            cookies=CookieJar(policy=NoCookies()),
            headers={"User-Agent": "SelfHostedWebTools/0.1", "Accept-Encoding": "identity"},
        )

    @asynccontextmanager
    async def stream(
        self, url: str, *, headers: dict | None = None, follow_redirects: bool = True
    ) -> AsyncIterator[httpx.Response]:
        current = url
        for _ in range(6):
            self.policy.validate_url(current)
            async with self.client.stream("GET", current, headers=headers) as response:
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ToolError(
                        "unsupported_content_encoding",
                        "Upstream ignored identity "
                        "encoding; compressed responses are blocked to bound memory use",
                    )
                if follow_redirects and response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ToolError("invalid_redirect", "Redirect has no Location header")
                    current = urljoin(str(response.url), location)
                    # Do not forward cookies/authorization across redirect origins.
                    headers = None
                    continue
                if response.status_code >= 400:
                    raise ToolError(
                        "upstream_http_error",
                        f"Upstream returned HTTP {response.status_code}.",
                        retryable=response.status_code in {429, 500, 502, 503, 504},
                    )
                yield response
                return
        raise ToolError("too_many_redirects", "Redirect limit exceeded")

    async def read(
        self, url: str, limit: int, *, headers: dict | None = None, follow_redirects: bool = True
    ):
        async with self.stream(url, headers=headers, follow_redirects=follow_redirects) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > limit:
                    raise ToolError(
                        "response_too_large", "Upstream response exceeds the byte limit"
                    )
                body.extend(chunk)
            return response, bytes(body)

    async def close(self):
        await self.client.aclose()
