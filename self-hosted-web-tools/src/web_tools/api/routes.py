import inspect

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def tool_routes(registry) -> APIRouter:
    router = APIRouter(prefix="/api/tools")
    for tool in registry.tools.values():

        def make_endpoint(current):
            async def endpoint(body):
                result = await registry.call(current.name, body.model_dump())
                return JSONResponse(result, status_code=200 if result["success"] else 400)

            endpoint.__signature__ = inspect.Signature(
                [
                    inspect.Parameter(
                        "body", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=current.schema
                    )
                ]
            )
            return endpoint

        router.add_api_route(
            f"/{tool.name}",
            make_endpoint(tool),
            methods=["POST"],
            name=tool.name,
            summary=tool.description,
        )
    return router
