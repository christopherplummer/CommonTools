from urllib.parse import unquote, urlsplit

from web_tools.security.download_policy import safe_filename


class DownloadService:
    def __init__(self, http, files, metadata):
        self.http = http
        self.files = files
        self.metadata = metadata

    async def download(self, url: str, filename: str | None = None) -> dict:
        filename = safe_filename(
            filename or unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "download.bin"
        )
        async with self.http.stream(url) as response:
            return await self.files.save(
                response.aiter_bytes(),
                url=url,
                filename=filename,
                content_type=response.headers.get("content-type", "application/octet-stream"),
            )

    async def inspect(self, file_id: str) -> dict:
        _, metadata = await self.files.path_for(file_id)
        return metadata

    async def list(self, limit: int = 20, offset: int = 0) -> dict:
        return await self.metadata.list(limit, offset)
