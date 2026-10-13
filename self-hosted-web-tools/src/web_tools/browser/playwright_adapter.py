"""All Chromium HTTP traffic is fulfilled by the pinned, policy-aware HTTP adapter."""

import logging

import httpx
from playwright.async_api import async_playwright

from web_tools.common.errors import ToolError

logger = logging.getLogger(__name__)


class PlaywrightAdapter:
    def __init__(self, settings, http):
        self.settings = settings
        self.http = http
        self.playwright = None
        self.browser = None

    async def start(self):
        if not self.settings.browser_enabled:
            return
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(
                headless=self.settings.browser_headless,
                # Fail closed for traffic missed by routing; HTTPX is the only egress path.
                proxy={"server": "http://127.0.0.1:9", "bypass": "<-loopback>"},
                args=[
                    "--disable-background-networking",
                    "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
            )
        except BaseException:
            await self.playwright.stop()
            self.playwright = None
            raise

    async def context(self):
        if not self.browser:
            raise ToolError("browser_disabled", "Browser support is disabled")
        context = await self.browser.new_context(
            accept_downloads=True,
            service_workers="block",
            permissions=[],
            viewport={"width": 1280, "height": 900},
        )
        context.set_default_timeout(self.settings.http_request_timeout_seconds * 1000)
        await context.route("**/*", self.route)
        await context.route_web_socket("**/*", lambda ws: ws.close())
        await context.add_init_script("""
            window.__webtoolsVersion = 0;
            new MutationObserver(() => { window.__webtoolsVersion++; }).observe(document, {
                childList: true, subtree: true, attributes: true, characterData: true
            });
        """)
        return context

    async def route(self, route, request):
        try:
            if request.method != "GET":
                raise ToolError("blocked_method", "Browser traffic is restricted to GET requests")
            headers = await request.all_headers()
            # The browser maintains its own context cookies; never reuse HTTPX cookies.
            headers = {
                key: value
                for key, value in headers.items()
                if key not in {"host", "connection", "accept-encoding", "authorization"}
            }
            response, body = await self.http.read(
                request.url,
                min(self.settings.browser_max_response_bytes, self.settings.max_download_bytes),
                headers=headers,
                follow_redirects=False,
            )
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key
                not in {
                    "content-encoding",
                    "content-length",
                    "transfer-encoding",
                    "connection",
                    "set-cookie",
                }
            }
            cookies = response.headers.get_list("set-cookie")
            if cookies:
                # Playwright's protocol accepts newline-separated Set-Cookie values.
                response_headers["set-cookie"] = "\n".join(cookies)
            await route.fulfill(status=response.status_code, headers=response_headers, body=body)
        except (ToolError, httpx.HTTPError):
            logger.info("browser_request_blocked_or_failed")
            await route.abort("blockedbyclient")

    def ready(self):
        return not self.settings.browser_enabled or bool(
            self.browser and self.browser.is_connected()
        )

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
