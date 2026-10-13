import hashlib

import pytest

from web_tools.common.errors import ToolError
from web_tools.security.download_policy import safe_filename
from web_tools.security.http_client import SafeHTTPClient
from web_tools.security.network_policy import NetworkPolicy
from web_tools.services.download_service import DownloadService
from web_tools.storage.file_store import FileStore
from web_tools.storage.metadata_store import MetadataStore


@pytest.mark.parametrize(
    "name",
    [
        "../file",
        "a/b",
        "a\\b",
        "C:\\file",
        "CON",
        "aux.txt",
        "file:stream",
        ".hidden",
        "x\0y",
        "x.",
        "x ",
        "..",
    ],
)
def test_filename_traversal(name):
    with pytest.raises(ToolError):
        safe_filename(name)


@pytest.mark.integration
async def test_persistence_no_overwrite_size_cleanup(settings, fixture_site):
    settings.test_allowed_origins = [fixture_site]
    settings.max_download_size_mb = 1
    http = SafeHTTPClient(NetworkPolicy(settings), 5)
    metadata = MetadataStore(settings.database_path)
    files = FileStore(settings, metadata)
    await metadata.start()
    await files.start()
    service = DownloadService(http, files, metadata)
    try:
        one = await service.download(f"{fixture_site}/manual.txt")
        two = await service.download(f"{fixture_site}/manual.txt")
        assert one["file_id"] != two["file_id"]
        assert one["storage_location"] != two["storage_location"]
        path, _ = await files.path_for(one["file_id"])
        assert one["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert one["size"] == path.stat().st_size
        with pytest.raises(ToolError, match="size limit"):
            await service.download(f"{fixture_site}/large")
        assert not list(files.directory.glob("*.partial"))
        await metadata.close()
        await metadata.start()
        assert (await service.inspect(one["file_id"]))["status"] == "complete"
        listing = await service.list(limit=1)
        assert len(listing["files"]) == 1 and listing["next_offset"] == 1
        assert len((await service.list())["files"]) == 2
    finally:
        await metadata.close()
        await http.close()


async def test_quota_and_interrupted_stream_cleanup(settings):
    settings.storage_quota_mb = 1
    metadata = MetadataStore(settings.database_path)
    files = FileStore(settings, metadata)
    await metadata.start()
    await files.start()

    async def too_large():
        yield b"x" * (1024 * 1024)
        yield b"x"

    async def interrupted():
        yield b"partial"
        raise ConnectionError("interrupted")

    try:
        with pytest.raises(ToolError, match="quota"):
            await files.save(
                too_large(),
                url="https://example.com",
                filename="big.bin",
                content_type="application/octet-stream",
            )
        with pytest.raises(ConnectionError):
            await files.save(
                interrupted(),
                url="https://example.com",
                filename="file.bin",
                content_type="application/octet-stream",
            )
        assert list(files.directory.iterdir()) == []
        assert (await metadata.list())["files"] == []
    finally:
        await metadata.close()
