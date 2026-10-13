import json
import re

import httpx

from web_tools.common.errors import ToolError
from web_tools.config import Settings


class SearchService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def search(self, query: str, limit: int = 5, language: str = "en") -> dict:
        body = bytearray()
        async with self.client.stream(
            "GET",
            f"{self.settings.searxng_base_url.rstrip('/')}/search",
            params={"q": query, "format": "json", "language": language},
        ) as response:
            if response.status_code != 200:
                raise ToolError(
                    "search_unavailable",
                    f"SearXNG returned HTTP {response.status_code}.",
                    retryable=response.status_code == 429 or response.status_code >= 500,
                )
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.settings.max_search_bytes:
                    raise ToolError("response_too_large", "Search response exceeds the byte limit")
        try:
            payload = json.loads(body)
            raw = payload.get("results", [])
            if not isinstance(raw, list):
                raise ValueError("Invalid result collection")
        except (ValueError, AttributeError) as exc:
            raise ToolError("invalid_search_response", "SearXNG returned invalid JSON") from exc
        results = []
        seen = set()
        shortened = False
        for item in raw:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            if not url.startswith(("http://", "https://")) or url in seen or len(url) > 4096:
                continue
            seen.add(url)
            snippet = re.sub(r"<[^>]+>", "", str(item.get("content", "")))
            shortened |= len(snippet) > 500 or len(str(item.get("title", ""))) > 200
            results.append(
                {
                    "title": str(item.get("title", ""))[:200],
                    "url": url,
                    "snippet": snippet[:500],
                    "engine": str(item["engine"])[:60] if item.get("engine") else None,
                }
            )
        failures = payload.get("unresponsive_engines", [])
        if not isinstance(failures, list):
            failures = []
        warnings = [
            {"engine": str(item[0])[:60], "reason": str(item[1])[:120]}
            for item in failures[:5]
            if isinstance(item, list) and len(item) >= 2
        ]
        if not results and warnings:
            raise ToolError(
                "search_engines_unavailable",
                "No results; upstream search engines failed: "
                + "; ".join(f"{item['engine']}: {item['reason']}" for item in warnings),
                retryable=True,
            )
        return {
            "query": query,
            "results": results[:limit],
            "warnings": warnings,
            "_truncated": len(results) > limit or shortened,
        }

    async def ready(self) -> bool:
        # JSON functionality is critical; a responding HTML UI alone is insufficient.
        try:
            await self.search("example", limit=1)
            return True
        except (ToolError, httpx.HTTPError):
            return False
