import json
from pathlib import Path

import aiosqlite

from web_tools.common.errors import ToolError


class MetadataStore:
    def __init__(self, path: Path):
        self.path = path
        self.connection: aiosqlite.Connection | None = None

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("""CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, metadata TEXT NOT NULL)""")
        await self.connection.commit()

    async def add(self, metadata: dict):
        await self.connection.execute(
            "INSERT INTO files VALUES (?, ?, ?)",
            (metadata["file_id"], metadata["downloaded_at"], json.dumps(metadata)),
        )
        await self.connection.commit()

    async def inspect(self, file_id: str) -> dict:
        async with self.connection.execute(
            "SELECT metadata FROM files WHERE id=?", (file_id,)
        ) as c:
            row = await c.fetchone()
        if row is None:
            raise ToolError(
                "file_not_found",
                "Unknown file ID; use file_list.",
                next_operation="file_list",
                status=404,
            )
        return json.loads(row[0])

    async def list(self, limit: int = 20, offset: int = 0) -> dict:
        async with self.connection.execute(
            "SELECT metadata FROM files ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit + 1, offset),
        ) as c:
            rows = await c.fetchall()
        return {
            "files": [json.loads(row[0]) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
            "_truncated": len(rows) > limit,
        }

    async def ready(self):
        try:
            await self.connection.execute("SELECT 1")
            return True
        except (AttributeError, aiosqlite.Error):
            return False

    async def close(self):
        if self.connection:
            await self.connection.close()
