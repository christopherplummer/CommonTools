import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.routing import Route

from web_tools.api.routes import tool_routes
from web_tools.api.schemas import ApprovalInput
from web_tools.browser.playwright_adapter import PlaywrightAdapter
from web_tools.browser.session_manager import SessionManager
from web_tools.common.errors import ToolError
from web_tools.common.logging import configure_logging
from web_tools.config import Settings
from web_tools.dependencies import ToolRegistry
from web_tools.mcp.server import create_mcp
from web_tools.security.authorization import AuthenticationMiddleware
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.interaction_policy import InteractionPolicy
from web_tools.security.network_policy import NetworkPolicy
from web_tools.services.browser_service import BrowserService
from web_tools.services.download_service import DownloadService
from web_tools.services.fetch_service import FetchService
from web_tools.services.search_service import SearchService
from web_tools.storage.file_store import FileStore
from web_tools.storage.metadata_store import MetadataStore


def create_app(settings: Settings | None = None, *, search_transport=None, web_transport=None):
    settings = settings or Settings()
    search_client = httpx.AsyncClient(
        transport=search_transport, trust_env=False, timeout=settings.http_request_timeout_seconds
    )
    policy = NetworkPolicy(settings)
    http = SafeHTTPClient(policy, settings.http_request_timeout_seconds, web_transport)
    search = SearchService(settings, search_client)
    fetch = FetchService(settings, http)
    registry = ToolRegistry(
        search, fetch, settings.tool_timeout_seconds, settings.max_tool_response_chars
    )
    metadata = MetadataStore(settings.database_path)
    files = FileStore(settings, metadata)
    downloads = DownloadService(http, files, metadata)
    interactions = InteractionPolicy(settings)
    adapter = PlaywrightAdapter(settings, http)
    sessions = SessionManager(settings, adapter)
    browser = BrowserService(settings, sessions, policy, interactions, files)
    registry.add_downloads(downloads)
    if settings.browser_enabled:
        registry.add_browser(browser)
    _, manager = create_mcp(registry, settings)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging(settings.log_level)
        async with AsyncExitStack() as stack:
            stack.push_async_callback(search_client.aclose)
            stack.push_async_callback(http.close)
            stack.push_async_callback(metadata.close)
            await metadata.start()
            await files.start()
            stack.push_async_callback(adapter.close)
            await adapter.start()
            stack.push_async_callback(sessions.close)
            await sessions.start()
            await stack.enter_async_context(manager.run())
            yield

    app = FastAPI(title="Self-hosted Web Tools", version="0.1.0", lifespan=lifespan)
    app.state.registry = registry
    app.state.settings = settings
    app.state.search = search
    app.state.files = files
    app.state.browser = browser
    app.add_middleware(AuthenticationMiddleware, key=settings.api_key.get_secret_value())
    app.include_router(tool_routes(registry))

    @app.exception_handler(ToolError)
    async def tool_error(request, exc):
        return JSONResponse(
            {
                "success": False,
                "data": None,
                "metadata": {"duration_ms": 0, "truncated": False},
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "next_operation": exc.next_operation,
                },
            },
            status_code=exc.status,
        )

    @app.get("/api/files/{file_id}/content")
    async def artifact(file_id: str):
        path, info = await files.path_for(file_id)
        return FileResponse(
            path,
            media_type=info["content_type"],
            filename=info["filename"],
            headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"},
        )

    @app.post("/api/approvals")
    async def approve(body: ApprovalInput, x_human_approval_key: str = Header("")):
        # This route is intentionally not exposed as an MCP tool.
        async with sessions.use(body.session_id) as session:
            await browser.reference(session, body.ref)
            return interactions.approve(
                x_human_approval_key, body.action, body.session_id, body.ref, body.text
            )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "success": False,
                "data": None,
                "metadata": {"truncated": False},
                "error": {
                    "code": "invalid_arguments",
                    "retryable": False,
                    "message": "Request does not match tool schema; see /docs.",
                },
            },
            status_code=422,
        )

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        searx_ok, database_ok, storage_ok = await asyncio.gather(
            search.ready(), metadata.ready(), files.ready()
        )
        dependencies = {
            "searxng": searx_ok,
            "database": database_ok,
            "storage": storage_ok,
            "browser": adapter.ready(),
        }
        ok = all(dependencies.values())
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "dependencies": dependencies},
            status_code=200 if ok else 503,
        )

    # Route directly, with no trailing-slash redirect; the host owns MCP's lifespan.
    class MCPEndpoint:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    app.router.routes.append(
        Route("/mcp", endpoint=MCPEndpoint(), methods=["GET", "POST", "DELETE"])
    )
    return app
