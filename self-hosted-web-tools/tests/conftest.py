import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from web_tools.config import Settings

API_KEY = "test-api-key-with-at-least-24-characters"
APPROVAL_KEY = "test-human-key-with-at-least-24-characters"
PAGE = b"""<!doctype html><html><head><title>Fixture Docs</title>
<link rel="canonical" href="/docs"></head><body><main><h1>Fixture documentation</h1>
<p>This is deterministic documentation about a self-hosted web tools service.
Search, extract readable text, follow documentation links, and save a manual.</p>
<a href="/guide">Read guide</a><a href="/manual.txt" download>Download manual</a>
<label for="query">Search docs</label><input id="query" aria-label="Search docs">
<button onclick="document.getElementById('result').textContent='clicked'">Test button</button>
<p id="result"></p></main></body></html>"""


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        api_key=API_KEY,
        human_approval_key=APPROVAL_KEY,
        download_directory=tmp_path / "downloads",
        database_url=f"sqlite:///{tmp_path / 'webtools.db'}",
        browser_enabled=False,
        environment="test",
    )


@pytest.fixture
def search_transport():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "content": "A <b>snippet</b>",
                        "engine": "fixture",
                    },
                    {"title": "Duplicate", "url": "https://example.com"},
                    {"title": "Other", "url": "https://example.org", "content": "other"},
                ]
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def pdf_bytes():
    """Build real PDF bytes with a standard font and extractable page text."""

    def build(texts=("First PDF page", "Second PDF page"), *, encrypted=False, compressed=False):
        writer = PdfWriter()
        font = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
        )
        for text in texts:
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            content = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode("ascii"))
            if compressed:
                content = content.flate_encode()
            page[NameObject("/Contents")] = writer._add_object(content)
        if encrypted:
            writer.encrypt("fixture-password")
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    return build


@pytest.fixture
def fixture_site(pdf_bytes):
    manual = pdf_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/search"):
                body = json.dumps(
                    {
                        "results": [
                            {
                                "title": "Fixture Docs",
                                "url": f"http://127.0.0.1:{self.server.server_port}/docs",
                                "content": "Documentation",
                                "engine": "fixture",
                            }
                        ]
                    }
                ).encode()
                content_type = "application/json"
            elif self.path == "/private-redirect":
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.end_headers()
                return
            elif self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/docs")
                self.end_headers()
                return
            elif self.path == "/manual.txt":
                body, content_type = b"Fixture manual: deterministic download.\n", "text/plain"
            elif self.path == "/manual.pdf":
                body, content_type = manual, "application/pdf"
            elif self.path == "/large":
                body, content_type = b"x" * (2 * 1024 * 1024), "application/octet-stream"
            elif self.path == "/guide":
                body = (
                    b"<html><title>Guide</title><p>Read the manual.</p>"
                    b'<a href="/manual.txt" download>Download manual</a></html>'
                )
                content_type = "text/html"
            else:
                body, content_type = PAGE, "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if self.path == "/manual.txt":
                self.send_header("Content-Disposition", 'attachment; filename="manual.txt"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
