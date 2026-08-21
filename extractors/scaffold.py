"""Scaffold generator for new DataHarbor extractors."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from extractors.validator import ExtractorValidator

EXTRACTORS_DIR = os.path.dirname(os.path.abspath(__file__))


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", (name or "").strip()).strip("_").lower()
    if not cleaned or not cleaned.isidentifier() or cleaned[0].isdigit():
        raise ValueError(
            f"Invalid extractor name '{name}'. Use a Python identifier "
            "(letters/digits/underscore, not starting with a digit)."
        )
    return cleaned


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def create_extractor(
    name: str,
    *,
    description: Optional[str] = None,
    domains: Optional[List[str]] = None,
    target_dir: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Create a minimal valid extractor scaffold.

    Default location: ``extractors/<name>/``.
    Use ``target_dir`` to scaffold into a private-repo working copy.
    """
    extractor_name = _normalize_name(name)
    root = (
        os.path.abspath(target_dir)
        if target_dir
        else os.path.join(EXTRACTORS_DIR, extractor_name)
    )

    if os.path.exists(root):
        if not force:
            raise ValueError(
                f"Extractor path already exists: {root}. Use --force to overwrite."
            )
        import shutil

        shutil.rmtree(root)

    os.makedirs(root, exist_ok=True)
    domain_list = domains or [f"{extractor_name}.example"]
    desc = description or f"HTML parser for {', '.join(domain_list)}"

    manifest = {
        "name": extractor_name,
        "version": "0.1.0",
        "description": desc,
        "domains": domain_list,
        "entrypoint": "extractor:parse",
        "capabilities": ["parse_directory"],
    }
    _write(os.path.join(root, "manifest.json"), json.dumps(manifest, indent=2) + "\n")
    _write(os.path.join(root, "__init__.py"), f'"""Extractor package: {extractor_name}."""\n')

    code = f'''"""Extractor scaffold for `{extractor_name}` — parse only, no HTTP."""
from typing import Any, Dict, List

from bs4 import BeautifulSoup


def parse(html: str, source_url: str) -> List[Dict[str, Any]]:
    """Parse already-fetched HTML into structured records.

    Contract:
    - input: raw HTML + source URL
    - output: list of dicts; include ``source_url`` on each record
    - do not perform HTTP / proxy / browser control here
    """
    soup = BeautifulSoup(html or "", "html.parser")
    results: List[Dict[str, Any]] = []

    # TODO: replace selectors for your target site
    for node in soup.select("h1, h2, h3, .card, .item"):
        title = node.get_text(" ", strip=True)
        if not title or len(title) < 2:
            continue
        results.append(
            {{
                "company_name": title,
                "website": None,
                "summary": title,
                "source_directory": "{extractor_name}",
                "source_url": source_url,
            }}
        )
    return results


def generate_page_urls(base_url: str, max_pages: int = 10) -> List[str]:
    """Optional pagination helper used by registry.generate_page_urls_for_domain."""
    urls = [base_url]
    limit = 10 if max_pages <= 0 else max_pages
    delim = "&" if "?" in base_url else "?"
    for page in range(1, limit):
        urls.append(f"{{base_url}}{{delim}}page={{page}}")
    return urls
'''
    _write(os.path.join(root, "extractor.py"), code)

    is_valid, errors = ExtractorValidator(root).validate()
    if not is_valid:
        raise ValueError(
            "Scaffold created but failed validation:\n  - " + "\n  - ".join(errors)
        )

    try:
        from apps.scraper.extractors.registry import clear_registry_cache

        clear_registry_cache()
    except Exception:
        pass

    return {
        "status": "success",
        "extractor_name": extractor_name,
        "path": root,
        "files": ["manifest.json", "__init__.py", "extractor.py"],
        "message": f"Extractor scaffold '{extractor_name}' created at {root}",
    }
