"""Opt-in live service smoke test; failures are real failures, never replaced by fixtures."""

import argparse
import asyncio
import json
import os

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--public", action="store_true", help="Opt in to public internet requests")
    args = parser.parse_args()
    load_dotenv()
    key = os.environ["API_KEY"]
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, timeout=90) as http:
        live = await http.get(f"{args.base_url}/health/live")
        live.raise_for_status()
        ready = await http.get(f"{args.base_url}/health/ready")
        print("readiness:", ready.json())
        ready.raise_for_status()
        async with streamable_http_client(f"{args.base_url}/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("MCP tools:", ", ".join(t.name for t in tools.tools))
                if args.public:
                    for name, arguments in [
                        ("web_search", {"query": "Python Playwright documentation", "limit": 3}),
                        ("web_fetch", {"url": "https://example.com", "max_chars": 1000}),
                        (
                            "file_download",
                            {"url": "https://example.com", "filename": "example.html"},
                        ),
                    ]:
                        result = await session.call_tool(name, arguments)
                        data = result.structuredContent
                        print(name, json.dumps(data, separators=(",", ":")))
                        if result.isError or not data["success"]:
                            raise RuntimeError(f"{name} failed")
                        if name == "web_search" and not data["data"]["results"]:
                            raise RuntimeError("Live search returned no results")
                    if "browser_open" in {tool.name for tool in tools.tools}:
                        opened = await session.call_tool(
                            "browser_open", {"url": "https://example.com"}
                        )
                        if opened.isError:
                            raise RuntimeError("Live browser open failed")
                        session_id = opened.structuredContent["data"]["session_id"]
                        try:
                            snapshot = await session.call_tool(
                                "browser_snapshot", {"session_id": session_id}
                            )
                            if snapshot.isError:
                                raise RuntimeError("Live browser snapshot failed")
                            print("browser_snapshot:", json.dumps(snapshot.structuredContent))
                        finally:
                            await session.call_tool("browser_close", {"session_id": session_id})


if __name__ == "__main__":
    asyncio.run(main())
