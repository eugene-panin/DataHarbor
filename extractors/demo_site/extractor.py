"""Extractor scaffold for `demo_site` — parse only, no HTTP."""
from typing import Any

from bs4 import BeautifulSoup


def parse(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse already-fetched HTML into structured records.

    Contract:
    - input: raw HTML + source URL
    - output: list of dicts; include ``source_url`` on each record
    - do not perform HTTP / proxy / browser control here
    """
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[dict[str, Any]] = []

    # TODO: replace selectors for your target site
    for node in soup.select("h1, h2, h3, .card, .item"):
        title = node.get_text(" ", strip=True)
        if not title or len(title) < 2:
            continue
        results.append(
            {
                "company_name": title,
                "website": None,
                "summary": title,
                "source_directory": "demo_site",
                "source_url": source_url,
            }
        )
    return results


def generate_page_urls(base_url: str, max_pages: int = 10) -> list[str]:
    """Optional pagination helper used by registry.generate_page_urls_for_domain."""
    urls = [base_url]
    limit = 10 if max_pages <= 0 else max_pages
    delim = "&" if "?" in base_url else "?"
    for page in range(1, limit):
        urls.append(f"{base_url}{delim}page={page}")
    return urls
