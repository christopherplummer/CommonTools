import asyncio

from lxml.etree import ParserError

from web_tools.common.errors import ToolError
from web_tools.config import Settings
from web_tools.security.http_client import SafeHTTPClient
from web_tools.services.extraction_service import extract_page


class FetchService:
    def __init__(self, settings: Settings, http: SafeHTTPClient):
        self.settings = settings
        self.http = http

    async def fetch(self, url: str, max_chars: int = 12000) -> dict:
        limit = min(max_chars, self.settings.max_fetch_chars)
        response, body = await self.http.read(url, self.settings.max_fetch_bytes)
        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        if content_type in {"text/html", "application/xhtml+xml"}:
            try:
                result = await asyncio.to_thread(extract_page, body, str(response.url), limit)
            except (ValueError, ParserError) as exc:
                raise ToolError("invalid_html", "Could not parse the HTML page") from exc
        elif content_type.startswith("text/"):
            text = body.decode(response.encoding or "utf-8", errors="replace")
            result = {
                "title": "",
                "canonical_url": str(response.url),
                "source_url": str(response.url),
                "text": text[:limit],
                "links": [],
                "untrusted_content": True,
                "_truncated": len(text) > limit,
            }
        else:
            raise ToolError(
                "unsupported_content_type",
                "Use file_download for binary content.",
                next_operation="file_download",
            )
        return {
            **result,
            "requested_url": url,
            "http_status": response.status_code,
            "content_type": content_type,
        }
