"""Internal, one-shot PDF parser. Arguments are supplied only by PDFService."""

import json
import logging
import sys
from pathlib import Path

from web_tools.common.errors import ToolError

STREAM_LIMIT = 10_000_000


def extract(
    path: Path,
    page_start: int,
    page_end: int,
    max_chars: int,
    text_offset: int,
    page_limit: int,
    max_bytes: int,
) -> dict:
    from pypdf import PdfReader, apply_configuration

    # Bound decompression and page-tree work as well as the input/output sizes.
    with (
        apply_configuration(
            maximum_declared_stream_length=STREAM_LIMIT,
            array_based_stream_maximum_output_length=STREAM_LIMIT,
            zlib_maximum_output_length=STREAM_LIMIT,
            lzw_maximum_output_length=STREAM_LIMIT,
            run_length_maximum_output_length=STREAM_LIMIT,
            brotli_maximum_output_length=STREAM_LIMIT,
            stream_decoding_work_maximum_length=STREAM_LIMIT * 3,
            page_tree_maximum_entries=10000,
            page_tree_maximum_depth=50,
        ),
        path.open("rb") as stream,
    ):
        stream.seek(0, 2)
        if stream.tell() > max_bytes:
            raise ToolError("pdf_too_large", "PDF exceeds PDF_MAX_FILE_SIZE_MB")
        stream.seek(0)
        if stream.read(1024).lstrip().find(b"%PDF-") < 0:
            raise ToolError("unsupported_content_type", "Saved file does not have a PDF header")
        stream.seek(0)
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ToolError(
                "encrypted_pdf", "Encrypted PDFs are unsupported; provide a decrypted PDF"
            )
        total = len(reader.pages)
        if not total or page_start > total or page_end > total:
            raise ToolError(
                "invalid_page_range", f"PDF contains {total} pages; choose a valid range"
            )
        end = page_end or min(total, page_start + min(5, page_limit) - 1)
        pages = []
        remaining = max_chars
        next_page, next_offset = None, 0
        truncated = False
        for number in range(page_start, end + 1):
            page = reader.pages[number - 1]
            contents = page.get_contents()
            if contents is not None and len(contents.get_data()) > STREAM_LIMIT:
                raise ToolError("pdf_resource_limit", "PDF page content exceeds the parsing limit")
            text = (page.extract_text() or "").strip()
            offset = text_offset if number == page_start else 0
            if offset > len(text):
                raise ToolError("invalid_text_offset", "text_offset exceeds the first page's text")
            selected = text[offset : offset + remaining]
            partial = offset + len(selected) < len(text)
            pages.append(
                {
                    "page_number": number,
                    "text": selected,
                    "text_offset": offset,
                    "has_text": bool(text),
                    "truncated": partial,
                }
            )
            remaining -= len(selected)
            if partial:
                next_page, next_offset, truncated = number, offset + len(selected), True
                break
            if not remaining and number < end:
                next_page, truncated = number + 1, True
                break
        if next_page is None and pages[-1]["page_number"] < total:
            next_page = pages[-1]["page_number"] + 1
        return {
            "total_pages": total,
            "pages": pages,
            "next_page": next_page,
            "next_text_offset": next_offset,
            "_truncated": truncated,
        }


def main():
    # Linux/container workers get an additional address-space ceiling. Native Windows
    # relies on input/decompression limits and the parent's killable timeout.
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    logging.disable(logging.CRITICAL)
    from pypdf.errors import LimitReachedError

    try:
        result = extract(Path(sys.argv[1]), *map(int, sys.argv[2:]))
    except ToolError as exc:
        result = {"error": {"code": exc.code, "message": exc.message}}
    except (MemoryError, RecursionError, LimitReachedError):
        result = {
            "error": {"code": "pdf_resource_limit", "message": "PDF exceeds safe parsing limits"}
        }
    except Exception:
        # Do not expose parser diagnostics, document content or internal paths.
        result = {"error": {"code": "invalid_pdf", "message": "PDF is malformed or unreadable"}}
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
