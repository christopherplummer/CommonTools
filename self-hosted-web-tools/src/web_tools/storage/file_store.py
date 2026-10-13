import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiofiles

from web_tools.common.errors import ToolError
from web_tools.security.download_policy import safe_filename


class FileStore:
    def __init__(self, settings, metadata):
        self.directory = settings.download_directory.resolve()
        self.max_bytes = settings.max_download_bytes
        self.quota_bytes = settings.storage_quota_mb * 1024 * 1024
        self.metadata = metadata
        self.lock = asyncio.Lock()

    async def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.partial"):
            path.unlink()

    async def usage(self):
        return await asyncio.to_thread(
            lambda: sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())
        )

    async def save(
        self,
        chunks: AsyncIterator[bytes],
        *,
        url: str,
        filename: str,
        content_type: str,
        kind: str = "download",
    ) -> dict:
        filename = safe_filename(filename)
        identifier = uuid4().hex
        storage_name = f"{identifier}_{filename}"
        destination = self.directory / storage_name
        partial = self.directory / f"{identifier}.partial"
        async with self.lock:
            used = await self.usage()
            size = 0
            digest = hashlib.sha256()
            try:
                async with aiofiles.open(partial, "xb") as file:
                    async for chunk in chunks:
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise ToolError("download_too_large", "Download exceeds the size limit")
                        if used + size > self.quota_bytes:
                            raise ToolError(
                                "storage_quota_exceeded", "Managed storage quota exceeded"
                            )
                        digest.update(chunk)
                        await file.write(chunk)
                await asyncio.to_thread(self.publish, partial, destination)
                metadata = {
                    "file_id": identifier,
                    "original_url": url,
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                    "sha256": digest.hexdigest(),
                    "downloaded_at": datetime.now(UTC).isoformat(),
                    "storage_location": storage_name,
                    "resource_uri": f"artifact://{identifier}",
                    "status": "complete",
                    "kind": kind,
                }
                await self.metadata.add(metadata)
                return metadata
            except BaseException:
                partial.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                raise

    @staticmethod
    def publish(partial: Path, destination: Path):
        destination.hardlink_to(partial)
        partial.unlink()

    async def path_for(self, file_id: str) -> tuple[Path, dict]:
        metadata = await self.metadata.inspect(file_id)
        path = (self.directory / metadata["storage_location"]).resolve()
        if path.parent != self.directory or not path.is_file():
            raise ToolError("file_not_found", "Artifact is unavailable", status=404)
        return path, metadata

    async def ready(self):
        probe = self.directory / f"{uuid4().hex}.partial"
        try:
            async with self.lock:
                async with aiofiles.open(probe, "xb") as file:
                    await file.write(b"")
                probe.unlink()
            return True
        except OSError:
            return False
