# Contributing to DataHarbor

Thanks for considering a contribution. This file covers the open-core
platform (`apps/`, `tests/`, docs, CI). Business bundles and site-specific
extractors are private by design — see [README.md § Architecture](README.md#-architecture-core--bundles--extractors)
and [AGENTS.md](AGENTS.md) for the core/bundle/extractor split.

## Before you start

- Check open issues and PRs first so effort doesn't overlap.
- For anything non-trivial (new CLI command, a new bundle template, a change
  to the manifest schema), open an issue to align on approach before writing
  code — it's a much shorter loop than a large PR getting re-designed in
  review.
- Bug fixes, doc fixes, and small clarifications can skip straight to a PR.

## Dev setup

```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh          # or: uv sync
uv run harbor doctor   # sanity-check your toolchain
```

Bring up the local stack and try the shipped demo bundle before you start
poking at platform internals — it's the fastest way to see the pieces fit
together:

```bash
uv run harbor up --compose
uv run harbor bundle run demo
uv run harbor bundle view demo
```

## Making a change

```bash
uv run ruff check apps bundles extractors tests   # lint (CI gate)
uv run pytest -q                                   # tests (CI gate)
uv run harbor bundle validate                       # manifest/contract checks
uv run harbor extractor validate
```

All four run in CI (`.github/workflows/ci.yml`) on every push/PR to `main`.
A PR that doesn't pass them won't merge, so it's worth running locally first.

Guidelines:

- Match the existing style — no type checker is enforced yet, but keep
  functions small and follow the patterns already in the module you're
  editing rather than introducing a new one.
- New platform behavior needs a test. `tests/` mirrors `apps/`; a new bundle
  scaffold template or CLI command should have a test alongside the existing
  ones for that module.
- Touching the bundle/extractor manifest contract (`apps/bundle/plugin_contract.py`,
  `apps/bundle/validator.py`)? Update `AGENTS.md` in the same PR — it's the
  contract AI agents and humans both read.
- Don't add secrets, real API keys, or scraped data to the repo, including
  in tests and fixtures. The `demo` bundle / `demo_site` extractor exist
  specifically so contributions can be demonstrated without either.

## Submitting a PR

- Keep PRs focused — one logical change per PR is easier to review and to
  revert if something's wrong.
- Describe *why*, not just *what*, in the PR description if the change isn't
  self-explanatory from the diff.
- Link the issue it addresses, if any.

## Reporting bugs / requesting features

Use the issue templates (`.github/ISSUE_TEMPLATE/`) — they ask for the
minimum needed to act on a report (repro steps, environment, expected vs.
actual behavior).

## Security issues

Do not open a public issue for a vulnerability — see [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you're expected to uphold it.
