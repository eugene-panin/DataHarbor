# demo_site — agent playbook

Contract example extractor. Parse-only HTML (`BeautifulSoup`). No HTTP.

- `parse(html, source_url) -> list[dict]` with `source_url` on each record
- Markup changes → patch `extractor.py`, not Core
