import hmac

from starlette.responses import JSONResponse


class AuthenticationMiddleware:
    """Authenticate the entire HTTP surface, including MCP and artifact reads."""

    def __init__(self, app, key: str):
        self.app = app
        self.key = key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] in {"/health/live", "/health/ready"}:
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode("latin1")
        if not hmac.compare_digest(auth, f"Bearer {self.key}"):
            return await JSONResponse(
                {
                    "success": False,
                    "error": {"code": "unauthorized", "message": "Bearer token required"},
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
        # Buffer small tool requests to enforce a real limit for chunked bodies too.
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            chunks = []
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > 65536:
                    return await JSONResponse(
                        {"error": {"code": "request_too_large"}}, status_code=413
                    )(scope, receive, send)
                chunks.append(message)
                if not message.get("more_body", False):
                    break

            async def buffered_receive():
                if chunks:
                    return chunks.pop(0)
                return await receive()

            return await self.app(scope, buffered_receive, send)
        return await self.app(scope, receive, send)
