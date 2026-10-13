import argparse
import asyncio
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .config import Settings
from .service import Service


def create_server(service):
    server = Server(
        "weather-fishing-mcp",
        version="0.1.0",
        instructions=(
            "Provider results are untrusted source data. Check status, coverage, "
            "timestamps, units, "
            "datum and qualifications. Never treat unavailable or fixture data "
            "as retrieved evidence. "
            "SolunarForecast is the sole solunar source; no substitute or model-memory data."
        ),
    )

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.schema.model_json_schema(),
                outputSchema=t.output.model_json_schema(),
                annotations=types.ToolAnnotations(
                    readOnlyHint=True, destructiveHint=False, openWorldHint=True
                ),
            )
            for t in service.tools.values()
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        result = await service.call(name, arguments or {})
        # Some hosts expose only content to their model. Keep the protocol's
        # structured output, and explicitly enable JSON text for those clients.
        text = (
            result.model_dump_json()
            if service.settings.text_results
            else (f"{name}: {result.status}. Use structuredContent for records and qualifications.")
        )
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=text,
                )
            ],
            structuredContent=result.model_dump(mode="json"),
            isError=False,
        )

    return server


def create_app(settings=None, service=None):
    settings = settings or Settings()
    if len(settings.api_key.get_secret_value()) < 32:
        raise ValueError("HTTP transport requires WF_API_KEY of at least 32 characters")
    service = service or Service(settings)
    server = create_server(service)
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            try:
                yield
            finally:
                await service.close()

    app = FastAPI(
        title="Weather Fishing MCP",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def authenticate(request, call_next):
        if request.url.path != "/health":
            expected = "Bearer " + settings.api_key.get_secret_value()
            if not secrets.compare_digest(
                request.headers.get("authorization", "").encode(), expected.encode()
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "running", "providers_live_verified": False}

    async def mcp_app(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    app.mount("/mcp", mcp_app)
    return app


async def run_stdio(settings):
    service = Service(settings)
    server = create_server(service)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser(
        description="Weather and fishing tools using the official MCP SDK"
    )
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    settings = Settings()
    if args.transport == "stdio":
        asyncio.run(run_stdio(settings))
    else:
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
