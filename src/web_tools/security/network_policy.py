import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from web_tools.common.errors import ToolError
from web_tools.config import Settings


class NetworkPolicy:
    def __init__(self, settings: Settings):
        self.ports = set(settings.allowed_ports)
        self.test_origins = set(settings.test_allowed_origins)

    def validate_url(self, url: str) -> tuple[str, int, bool]:
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Only absolute HTTP/HTTPS URLs are allowed")
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("URL credentials are not allowed")
            if any(ord(c) < 32 for c in url) or "\\" in url:
                raise ValueError("Invalid URL characters")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            test_exception = origin in self.test_origins
            if port not in self.ports and not test_exception:
                raise ValueError("Destination port is not allowed")
            host = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
            if "%" in host:
                raise ValueError("Scoped addresses are not allowed")
            if not test_exception:
                if host.lower() == "localhost" or host.lower().endswith(".localhost"):
                    raise ValueError("Local addresses are not allowed")
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address is not None and not self.is_public(address):
                    raise ValueError("Non-public addresses are not allowed")
            return host, port, test_exception
        except (ValueError, UnicodeError) as exc:
            raise ToolError("blocked_url", str(exc)) from exc

    @staticmethod
    def is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        # Exclude IPv6 transition/tunneling addresses that embed a private IPv4 target.
        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped:
                return NetworkPolicy.is_public(address.ipv4_mapped)
            if address.sixtofour or address.teredo:
                return False
            if address in ipaddress.ip_network("64:ff9b::/96"):
                return False
        return address.is_global and not address.is_multicast

    async def resolve(self, host: str, port: int, *, test_exception: bool = False) -> list[str]:
        try:
            records = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
                timeout=10,
            )
        except (OSError, TimeoutError) as exc:
            raise ToolError("dns_failed", "Cannot resolve destination.", retryable=True) from exc
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or (
            not test_exception
            and any(not self.is_public(ipaddress.ip_address(address)) for address in addresses)
        ):
            raise ToolError("blocked_address", "Destination resolves to a non-public address.")
        return addresses

    async def check(self, url: str) -> list[str]:
        host, port, exception = self.validate_url(url)
        return await self.resolve(host, port, test_exception=exception)
