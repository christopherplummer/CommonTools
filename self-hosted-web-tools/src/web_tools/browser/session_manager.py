import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from web_tools.common.errors import ToolError


@dataclass
class Session:
    identifier: str
    context: object
    page: object
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    refs: dict = field(default_factory=dict)
    snapshot_id: str | None = None
    snapshot_version: int = -1


class SessionManager:
    def __init__(self, settings, adapter):
        self.settings = settings
        self.adapter = adapter
        self.sessions: dict[str, Session] = {}
        self.lock = asyncio.Lock()
        self.cleanup_task = None

    async def start(self):
        self.cleanup_task = asyncio.create_task(self.reaper())

    async def create(self) -> Session:
        async with self.lock:
            if len(self.sessions) >= self.settings.browser_max_sessions:
                raise ToolError(
                    "session_limit",
                    "Close an existing browser session first.",
                    next_operation="browser_close",
                )
            context = await self.adapter.context()
            try:
                page = await context.new_page()
            except BaseException:
                await context.close()
                raise
            session = Session(uuid4().hex, context, page)
            page.on("framenavigated", lambda frame: session.refs.clear())
            # Initial implementation deliberately allows one page per context.
            context.on(
                "page", lambda popup: asyncio.create_task(popup.close()) if popup != page else None
            )
            self.sessions[session.identifier] = session
            return session

    @asynccontextmanager
    async def use(self, session_id: str):
        session = self.sessions.get(session_id)
        if session is None:
            raise ToolError(
                "session_not_found",
                "Session expired or closed; use browser_open.",
                next_operation="browser_open",
                status=404,
            )
        async with session.lock:
            if session_id not in self.sessions:
                raise ToolError(
                    "session_not_found",
                    "Session closed; use browser_open.",
                    next_operation="browser_open",
                )
            session.touched = time.monotonic()
            try:
                yield session
            finally:
                session.touched = time.monotonic()

    async def close_session(self, session_id: str):
        async with self.use(session_id) as session:
            await session.context.close()
            self.sessions.pop(session_id, None)

    async def reap(self):
        now = time.monotonic()
        for identifier, session in list(self.sessions.items()):
            if (
                not session.lock.locked()
                and now - session.touched > self.settings.browser_session_timeout_seconds
            ):
                await self.close_session(identifier)

    async def reaper(self):
        while True:
            await asyncio.sleep(10)
            await self.reap()

    async def close(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        for identifier in list(self.sessions):
            await self.close_session(identifier)
