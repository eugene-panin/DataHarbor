## What & why

<!-- What does this change, and why? Link an issue if there is one. -->

## How was this tested?

<!-- e.g. "uv run pytest -q", "ran harbor bundle run demo against docker compose", ... -->

## Checklist

- [ ] `uv run ruff check apps bundles extractors tests` passes
- [ ] `uv run pytest -q` passes
- [ ] `uv run harbor bundle validate` / `harbor extractor validate` pass (if you touched a bundle/extractor)
- [ ] Added or updated tests for the behavior change
- [ ] Updated `AGENTS.md` / `README.md` if this changes the platform contract or CLI surface
- [ ] No secrets, real API keys, or scraped data included in the diff
