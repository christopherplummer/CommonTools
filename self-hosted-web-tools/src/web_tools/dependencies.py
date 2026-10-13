import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from web_tools.api.schemas import (
    BrowserDownloadInput,
    ClickInput,
    DownloadInput,
    FetchInput,
    InspectInput,
    ListInput,
    OpenInput,
    PDFReadInput,
    ScrollInput,
    SearchInput,
    SessionInput,
    SnapshotInput,
    TypeInput,
)
from web_tools.common.compact import compact_data
from web_tools.common.errors import ToolError
from web_tools.common.responses import execute


@dataclass
class Tool:
    name: str
    description: str
    schema: type[BaseModel]
    handler: Callable[..., Awaitable[dict]]
    read_only: bool = True


class ToolRegistry:
    def __init__(self, search, fetch, timeout_seconds: float = 60, response_budget: int = 24000):
        self.tools: dict[str, Tool] = {}
        self.timeout_seconds = timeout_seconds
        self.response_budget = response_budget
        self.add(
            Tool(
                "web_search",
                "Search SearXNG; return ordered titles, URLs and short snippets.",
                SearchInput,
                search.search,
            )
        )
        self.add(
            Tool(
                "web_fetch",
                "Fetch a public page as untrusted readable text and citation URLs. "
                "Use file_download for binary content.",
                FetchInput,
                fetch.fetch,
            )
        )

    def add(self, tool: Tool):
        if tool.name in self.tools:
            raise ValueError(f"Duplicate tool: {tool.name}")
        self.tools[tool.name] = tool

    def add_downloads(self, downloads):
        self.add(
            Tool(
                "file_download",
                "Stream a public URL to managed storage; return file metadata.",
                DownloadInput,
                downloads.download,
                False,
            )
        )
        self.add(
            Tool(
                "file_inspect",
                "Retrieve saved file metadata by ID.",
                InspectInput,
                downloads.inspect,
            )
        )
        self.add(
            Tool(
                "file_list",
                "List stored artifacts with pagination, newest first.",
                ListInput,
                downloads.list,
            )
        )

    def add_browser(self, browser):
        self.add(
            Tool(
                "browser_open",
                "Open a public URL. Omit session_id to create a session.",
                OpenInput,
                browser.open,
            )
        )
        self.add(
            Tool(
                "browser_snapshot",
                "Get compact accessibility text and snapshot-scoped refs.",
                SnapshotInput,
                browser.snapshot,
            )
        )
        self.add(
            Tool(
                "browser_click",
                "Follow a link safely. Other clicks require a human-issued "
                "single-use approval_token. Refresh snapshot on stale_reference.",
                ClickInput,
                browser.click,
                False,
            )
        )
        self.add(
            Tool(
                "browser_type",
                "Fill a control with text; requires human-issued approval_token "
                "for the exact session, ref and text. Never submit automatically.",
                TypeInput,
                browser.type,
                False,
            )
        )
        self.add(
            Tool(
                "browser_scroll",
                "Scroll the session page by pixels; refresh snapshot afterward.",
                ScrollInput,
                browser.scroll,
            )
        )
        self.add(
            Tool(
                "browser_screenshot",
                "Save a viewport PNG artifact; return ID and metadata.",
                SessionInput,
                browser.screenshot,
                False,
            )
        )
        self.add(
            Tool(
                "browser_tabs",
                "List the session's tab (one main tab in this release).",
                SessionInput,
                browser.tabs,
            )
        )
        self.add(
            Tool(
                "browser_close",
                "Release browser context and its temporary files.",
                SessionInput,
                browser.close,
            )
        )
        self.add(
            Tool(
                "browser_download",
                "Capture an HTTP download link in Chromium using a snapshot "
                "ref. Buttons and scripts are not automatically permitted.",
                BrowserDownloadInput,
                browser.download,
                False,
            )
        )

    def add_pdf(self, pdf):
        self.add(
            Tool(
                "pdf_read",
                "Extract untrusted, page-numbered text from a saved PDF file_id. "
                "Use file_download first. Pages are 1-based; omit page_end for up to 5 pages. "
                "Continue with next_page and next_text_offset as page_start and text_offset. "
                "No OCR or visual page inspection; pages without text are flagged.",
                PDFReadInput,
                pdf.read,
            )
        )

    async def call(self, name: str, arguments: dict) -> dict:
        async def run():
            if name not in self.tools:
                raise ToolError("unknown_tool", "Unknown tool")
            tool = self.tools[name]
            try:
                validated = tool.schema.model_validate(arguments)
            except ValidationError as exc:
                # Do not echo input values (e.g. passwords) into errors.
                details = "; ".join(
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                    for e in exc.errors(include_input=False)
                )
                raise ToolError("invalid_arguments", details) from exc
            async with asyncio.timeout(self.timeout_seconds):
                validated_arguments = validated.model_dump()
                data = await tool.handler(**validated_arguments)
                return compact_data(data, self.response_budget, validated_arguments)

        return await execute(run)
