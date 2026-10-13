import base64
from contextlib import suppress
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import aiofiles
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout

from web_tools.common.errors import ToolError


class BrowserService:
    def __init__(self, settings, sessions, policy, interactions, files):
        self.settings = settings
        self.sessions = sessions
        self.policy = policy
        self.interactions = interactions
        self.files = files

    async def open(self, url: str, session_id: str | None = None):
        self.policy.validate_url(url)
        created = session_id is None
        if created:
            session_id = (await self.sessions.create()).identifier
        try:
            async with self.sessions.use(session_id) as session:
                session.refs.clear()
                try:
                    await session.page.goto(url, wait_until="domcontentloaded")
                except PlaywrightError as exc:
                    raise ToolError(
                        "navigation_failed",
                        "Navigation blocked or failed; verify URL.",
                        retryable=True,
                        next_operation="browser_open",
                    ) from exc
                return await self.page_info(session)
        except BaseException:
            if created:
                await self.sessions.close_session(session_id)
            raise

    async def page_info(self, session):
        return {
            "session_id": session.identifier,
            "url": session.page.url,
            "title": (await session.page.title())[:300],
            "tab_id": "main",
        }

    async def snapshot(self, session_id: str, max_chars: int = 8000):
        async with self.sessions.use(session_id) as session:
            session.refs.clear()
            session.snapshot_id = uuid4().hex[:12]
            version = await session.page.evaluate("window.__webtoolsVersion || 0")
            elements = []
            locator = session.page.locator(
                "a[href], button, input:not([type=hidden]), textarea, select, "
                "[role=button], [role=link], [role=textbox]"
            )
            total = await locator.count()
            for index in range(min(total, 80)):
                handle = await locator.nth(index).element_handle()
                if not handle or not await handle.is_visible():
                    continue
                attributes = await handle.evaluate("""e => ({
                    tag: e.tagName.toLowerCase(), role: e.getAttribute('role'),
                    name: (e.getAttribute('aria-label') || e.labels?.[0]?.textContent ||
                           e.textContent || e.getAttribute('placeholder') || '')
                           .trim().slice(0,120),
                    href: e.tagName === 'A' ? e.href : null,
                    input_type: e.getAttribute('type'), download: e.hasAttribute('download')
                })""")
                ref = f"{session.snapshot_id}:{index}"
                session.refs[ref] = (handle, attributes)
                elements.append({"ref": ref, **attributes})
            text = await session.page.locator("body").aria_snapshot()
            limit = min(max_chars, self.settings.max_fetch_chars)
            session.snapshot_version = version
            return {
                **await self.page_info(session),
                "snapshot_id": session.snapshot_id,
                "text": text[:limit],
                "elements": elements,
                "untrusted_content": True,
                "_truncated": len(text) > limit or total > 80,
            }

    async def reference(self, session, ref):
        entry = session.refs.get(ref)
        if not entry or session.snapshot_version != await session.page.evaluate(
            "window.__webtoolsVersion || 0"
        ):
            raise ToolError(
                "stale_reference",
                "Page changed; request a fresh browser_snapshot.",
                next_operation="browser_snapshot",
            )
        handle, attributes = entry
        if not await handle.evaluate("e => e.isConnected"):
            raise ToolError(
                "stale_reference",
                "Element detached; request browser_snapshot.",
                next_operation="browser_snapshot",
            )
        return handle, attributes

    async def click(self, session_id: str, ref: str, approval_token: str | None = None):
        async with self.sessions.use(session_id) as session:
            handle, attributes = await self.reference(session, ref)
            if attributes["tag"] == "a" and attributes["href"]:
                self.policy.validate_url(attributes["href"])
                # Safe navigation skips JS click handlers, even on apparent ordinary links.
                await session.page.goto(attributes["href"], wait_until="domcontentloaded")
            else:
                self.interactions.require(approval_token, "browser_click", session_id, ref)
                await handle.click(no_wait_after=True)
            session.refs.clear()
            return await self.page_info(session)

    async def type(self, session_id: str, ref: str, text: str, approval_token: str | None = None):
        async with self.sessions.use(session_id) as session:
            handle, _ = await self.reference(session, ref)
            self.interactions.require(approval_token, "browser_type", session_id, ref, text)
            await handle.fill(text)
            session.refs.clear()
            return {"session_id": session_id, "filled": True}

    async def scroll(self, session_id: str, pixels: int = 700):
        async with self.sessions.use(session_id) as session:
            await session.page.mouse.wheel(0, pixels)
            session.refs.clear()
            return await self.page_info(session)

    async def screenshot(self, session_id: str):
        async with self.sessions.use(session_id) as session:
            body = await session.page.screenshot(full_page=False, type="png")

            async def chunks():
                yield body

            return await self.files.save(
                chunks(),
                url=session.page.url,
                filename="screenshot.png",
                content_type="image/png",
                kind="screenshot",
            )

    async def tabs(self, session_id: str):
        async with self.sessions.use(session_id) as session:
            return {"session_id": session_id, "tabs": [await self.page_info(session)]}

    async def close(self, session_id: str):
        await self.sessions.close_session(session_id)
        return {"session_id": session_id, "closed": True}

    async def download(self, session_id: str, ref: str, filename: str | None = None):
        async with self.sessions.use(session_id) as session:
            handle, attributes = await self.reference(session, ref)
            if attributes["tag"] != "a" or not attributes["href"]:
                raise ToolError(
                    "unsafe_download_action", "Only HTTP/HTTPS download links are permitted"
                )
            self.policy.validate_url(attributes["href"])
            # Chromium may retry attachment requests outside Playwright routing.
            # Materialize bounded bytes through the safe adapter, then capture a real
            # browser Blob download. This keeps its network path fail-closed.
            cookies = await session.context.cookies(attributes["href"])
            cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            response, body = await self.sessions.adapter.http.read(
                attributes["href"],
                min(self.settings.browser_max_response_bytes, self.settings.max_download_bytes),
                headers={"Cookie": cookie_header},
            )
            suggested = (
                filename
                or unquote(urlsplit(attributes["href"]).path.rsplit("/", 1)[-1])
                or "download.bin"
            )
            blob_url = None
            try:
                async with session.page.expect_download() as event:
                    blob_url = await session.page.evaluate(
                        """({encoded, filename, contentType}) => {
                        const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
                        const url = URL.createObjectURL(new Blob([bytes], {type: contentType}));
                        const a = document.createElement('a'); a.href = url;
                        a.download = filename; a.click(); return url;
                    }""",
                        {
                            "encoded": base64.b64encode(body).decode(),
                            "filename": suggested,
                            "contentType": response.headers.get(
                                "content-type", "application/octet-stream"
                            ),
                        },
                    )
                download = await event.value
                error = await download.failure()
                if error:
                    raise ToolError("download_failed", "Browser download failed", retryable=True)
                path = await download.path()

                async def chunks():
                    async with aiofiles.open(path, "rb") as file:
                        while chunk := await file.read(65536):
                            yield chunk

                return await self.files.save(
                    chunks(),
                    url=attributes["href"],
                    filename=filename or download.suggested_filename,
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                    kind="browser_download",
                )
            except PlaywrightTimeout as exc:
                raise ToolError(
                    "download_not_started",
                    "Link did not initiate a download; use file_download with its URL.",
                    next_operation="file_download",
                ) from exc
            finally:
                session.refs.clear()
                if "download" in locals():
                    with suppress(PlaywrightError):
                        await download.delete()
                if blob_url:
                    with suppress(PlaywrightError):
                        await session.page.evaluate("url => URL.revokeObjectURL(url)", blob_url)
