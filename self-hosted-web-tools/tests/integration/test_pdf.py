import asyncio
import json
import sys

import pytest

from web_tools.common.compact import compact_data
from web_tools.common.errors import ToolError
from web_tools.services.pdf_service import PDFService
from web_tools.storage.file_store import FileStore
from web_tools.storage.metadata_store import MetadataStore


@pytest.fixture
async def pdf_store(settings):
    metadata = MetadataStore(settings.database_path)
    files = FileStore(settings, metadata)
    await metadata.start()
    await files.start()
    try:
        yield PDFService(settings, files), files
    finally:
        await metadata.close()


async def save(files, content, filename="manual.pdf", content_type="application/pdf"):
    async def chunks():
        yield content

    return await files.save(
        chunks(), url="https://example.com/manual.pdf", filename=filename, content_type=content_type
    )


@pytest.mark.integration
async def test_pages_and_continuation(pdf_store, pdf_bytes):
    pdf, files = pdf_store
    texts = [f"Page {number} documentation" for number in range(1, 7)]
    artifact = await save(files, pdf_bytes(texts))
    first = await pdf.read(artifact["file_id"])
    assert first["total_pages"] == 6
    assert [page["text"] for page in first["pages"]] == texts[:5]
    assert first["next_page"] == 6 and first["next_text_offset"] == 0
    assert first["source_url"] == artifact["original_url"] and first["untrusted"]
    last = await pdf.read(artifact["file_id"], page_start=6)
    assert last["pages"][0]["page_number"] == 6
    assert last["pages"][0]["text"] == texts[-1] and last["next_page"] is None
    selected = await pdf.read(artifact["file_id"], page_start=2, page_end=3)
    assert [page["text"] for page in selected["pages"]] == texts[1:3]


@pytest.mark.integration
async def test_long_page_can_be_read_without_lost_text(pdf_store, pdf_bytes):
    pdf, files = pdf_store
    text = "PDF documentation " * 30
    artifact = await save(files, pdf_bytes([text]))
    parts = []
    offset = 0
    for _ in range(10):
        result = await pdf.read(artifact["file_id"], max_chars=100, text_offset=offset)
        parts.append(result["pages"][0]["text"])
        if result["next_page"] is None:
            break
        assert result["_truncated"] and result["next_text_offset"] > offset
        offset = result["next_text_offset"]
    else:
        pytest.fail("PDF continuation failed to reach the end")
    assert "".join(parts) == text.strip()


@pytest.mark.integration
async def test_global_character_limit_and_blank_page(pdf_store, pdf_bytes, settings):
    pdf, files = pdf_store
    settings.max_fetch_chars = 100
    artifact = await save(files, pdf_bytes(["", "x" * 250]))
    result = await pdf.read(artifact["file_id"], max_chars=10000)
    assert result["pages"][0]["has_text"] is False
    assert result["pages"][0]["text"] == ""
    assert len(result["pages"][1]["text"]) == 100
    assert result["next_page"] == 2 and result["next_text_offset"] == 100


@pytest.mark.integration
async def test_pdf_header_overrides_filename_and_mime(pdf_store, pdf_bytes):
    pdf, files = pdf_store
    artifact = await save(files, pdf_bytes(), "download.bin", "application/octet-stream")
    assert (await pdf.read(artifact["file_id"]))["pages"][0]["text"] == "First PDF page"


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("encrypted", "encrypted_pdf"),
        ("malformed", "invalid_pdf"),
        ("html", "unsupported_content_type"),
        ("oversized", "pdf_too_large"),
    ],
)
async def test_unreadable_files_are_recoverable(pdf_store, pdf_bytes, settings, kind, code):
    pdf, files = pdf_store
    settings.pdf_max_file_size_mb = 1
    content = {
        "encrypted": pdf_bytes(encrypted=True),
        "malformed": b"%PDF-1.7\ncorrupt",
        "html": b"<html>This is not a PDF</html>",
        "oversized": pdf_bytes() + b" " * (1024 * 1024),
    }[kind]
    artifact = await save(files, content)
    with pytest.raises(ToolError) as exc:
        await pdf.read(artifact["file_id"])
    assert exc.value.code == code


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"page_start": 2, "page_end": 1}, "invalid_page_range"),
        ({"page_start": 3}, "invalid_page_range"),
        ({"page_end": 3}, "invalid_page_range"),
        ({"text_offset": 999}, "invalid_text_offset"),
        ({"page_end": 21}, "pdf_page_limit"),
    ],
)
async def test_range_limits(pdf_store, pdf_bytes, arguments, code):
    pdf, files = pdf_store
    artifact = await save(files, pdf_bytes())
    with pytest.raises(ToolError) as exc:
        await pdf.read(artifact["file_id"], **arguments)
    assert exc.value.code == code


async def test_missing_and_removed_artifacts(pdf_store, pdf_bytes):
    pdf, files = pdf_store
    with pytest.raises(ToolError) as exc:
        await pdf.read("0" * 32)
    assert exc.value.code == "file_not_found"
    artifact = await save(files, pdf_bytes())
    path, _ = await files.path_for(artifact["file_id"])
    path.unlink()
    with pytest.raises(ToolError) as exc:
        await pdf.read(artifact["file_id"])
    assert exc.value.code == "file_not_found"


async def test_compressed_pdf_content_limit(pdf_store, pdf_bytes):
    pdf, files = pdf_store
    artifact = await save(files, pdf_bytes(["x" * 10_000_001], compressed=True))
    assert artifact["size"] < 100000
    with pytest.raises(ToolError) as exc:
        await pdf.read(artifact["file_id"])
    assert exc.value.code == "pdf_resource_limit"


async def test_default_range_respects_page_limit(pdf_store, pdf_bytes, settings):
    pdf, files = pdf_store
    settings.pdf_max_pages_per_call = 1
    artifact = await save(files, pdf_bytes())
    result = await pdf.read(artifact["file_id"])
    assert len(result["pages"]) == 1 and result["next_page"] == 2


async def test_deadline_kills_parser(pdf_store, pdf_bytes, monkeypatch, settings):
    pdf, files = pdf_store
    artifact = await save(files, pdf_bytes())
    spawn = asyncio.create_subprocess_exec
    children = []

    async def slow_parser(*args, **kwargs):
        child = await spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_parser)
    settings.tool_timeout_seconds = 0.5
    with pytest.raises(TimeoutError):
        await pdf.read(artifact["file_id"])
    assert children and children[0].returncode is not None


def test_pdf_response_budget_preserves_continuation():
    data = {
        "file_id": "a" * 32,
        "total_pages": 2,
        "pages": [
            {
                "page_number": 1,
                "text": "short",
                "text_offset": 0,
                "has_text": True,
                "truncated": False,
            },
            {
                "page_number": 2,
                "text": "\u6587" * 2000,
                "text_offset": 80,
                "has_text": True,
                "truncated": False,
            },
        ],
        "next_page": None,
        "next_text_offset": 0,
    }
    result = compact_data(data, 4000, {})
    assert len(json.dumps(result, separators=(",", ":"))) <= 4000
    assert result["_truncated"] and result["next_page"] == 2
    assert result["next_text_offset"] == 80 + len(result["pages"][-1]["text"])
    assert result["pages"][-1]["truncated"] and result["pages"][0]["text"] == "short"
