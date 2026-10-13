import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from playwright.async_api import Error as BrowserError

from web_tools.common.errors import ToolError

logger = logging.getLogger(__name__)


async def execute(operation: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    start = time.monotonic()
    try:
        data = await operation()
        truncated = data.pop("_truncated", False)
        return {
            "success": True,
            "data": data,
            "metadata": {
                "duration_ms": round((time.monotonic() - start) * 1000),
                "truncated": truncated,
            },
            "error": None,
        }
    except ToolError as exc:
        error = {
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
            "next_operation": exc.next_operation,
        }
    except (httpx.TimeoutException, TimeoutError):
        error = {
            "code": "timeout",
            "message": "Upstream request timed out; retry later.",
            "retryable": True,
            "next_operation": None,
        }
    except httpx.HTTPError:
        error = {
            "code": "upstream_unavailable",
            "message": "Upstream connection failed.",
            "retryable": True,
            "next_operation": None,
        }
    except BrowserError:
        error = {
            "code": "browser_operation_failed",
            "message": "Browser operation failed; refresh the snapshot or reopen the page.",
            "retryable": True,
            "next_operation": "browser_snapshot",
        }
    except Exception:
        logger.exception("tool_execution_failed")
        error = {
            "code": "internal_error",
            "message": "Operation failed; inspect server logs.",
            "retryable": False,
            "next_operation": None,
        }
    return {
        "success": False,
        "data": None,
        "metadata": {"duration_ms": round((time.monotonic() - start) * 1000), "truncated": False},
        "error": error,
    }
