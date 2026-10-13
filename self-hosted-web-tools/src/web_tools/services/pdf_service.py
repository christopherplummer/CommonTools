"""Read managed PDFs in a cancellable parser process, never in the event loop."""

import asyncio
import json
import sys

from web_tools.common.errors import ToolError


class PDFService:
    def __init__(self, settings, files):
        self.settings = settings
        self.files = files
        self.lock = asyncio.Lock()

    async def read(
        self,
        file_id: str,
        page_start: int = 1,
        page_end: int | None = None,
        max_chars: int = 12000,
        text_offset: int = 0,
    ) -> dict:
        page_limit = self.settings.pdf_max_pages_per_call
        if page_end is not None and page_end < page_start:
            raise ToolError("invalid_page_range", "page_end must be at least page_start")
        if page_end is not None and page_end - page_start + 1 > page_limit:
            raise ToolError("pdf_page_limit", f"Read at most {page_limit} pages per call")
        path, metadata = await self.files.path_for(file_id)
        max_bytes = self.settings.pdf_max_file_size_mb * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise ToolError("pdf_too_large", "PDF exceeds PDF_MAX_FILE_SIZE_MB")
        async with self.lock, asyncio.timeout(self.settings.tool_timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "web_tools.services.pdf_worker",
                str(path),
                str(page_start),
                str(page_end or 0),
                str(min(max_chars, self.settings.max_fetch_chars)),
                str(text_offset),
                str(page_limit),
                str(max_bytes),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                output, _ = await process.communicate()
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            if process.returncode:
                raise ToolError(
                    "pdf_resource_limit",
                    "PDF parser exited before completing within resource limits",
                )
            try:
                result = json.loads(output)
            except (ValueError, UnicodeError) as exc:
                raise ToolError("invalid_pdf", "PDF parser could not read this document") from exc
        if "error" in result:
            raise ToolError(result["error"]["code"], result["error"]["message"])
        return {
            "file_id": file_id,
            "filename": metadata["filename"],
            "source_url": metadata["original_url"],
            "untrusted": True,
            **result,
        }
