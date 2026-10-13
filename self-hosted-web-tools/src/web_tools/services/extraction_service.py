from urllib.parse import urljoin

import trafilatura
from lxml import html


def extract_page(body: bytes, url: str, max_chars: int) -> dict:
    document = html.fromstring(body)
    title = " ".join(document.xpath("//title/text()"))[:300]
    canonical = document.xpath(
        '//link[contains(concat(" ", normalize-space(@rel), " "), " canonical ")]/@href'
    )
    links = []
    seen = set()
    for node in document.xpath("//a[@href]"):
        destination = urljoin(url, node.get("href"))
        if (
            destination.startswith(("http://", "https://"))
            and len(destination) <= 4096
            and destination not in seen
        ):
            seen.add(destination)
            links.append({"text": " ".join(node.text_content().split())[:120], "url": destination})
    text = trafilatura.extract(body, url=url, include_comments=False, include_tables=True) or ""
    if not text:
        for node in document.xpath("//script|//style|//nav|//footer"):
            node.drop_tree()
        text = " ".join(document.text_content().split())
    canonical_url = urljoin(url, canonical[0]) if canonical else url
    if not canonical_url.startswith(("http://", "https://")) or len(canonical_url) > 4096:
        canonical_url = url
    return {
        "title": title,
        "canonical_url": canonical_url,
        "source_url": url,
        "text": text[:max_chars],
        "links": links[:30],
        "untrusted_content": True,
        "_truncated": len(text) > max_chars or len(links) > 30,
    }
