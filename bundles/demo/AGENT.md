# demo — agent playbook

Not a platform skill. Use `dataharbor-bundle-designer` / `operator` / `remediator`.

## What it is

Reference bundle shipped with open-core: scrapes the local `demo_site` Docker
Compose fixture (`deploy/demo_site/`) into PostgreSQL, no API keys or external
network needed. Exists to prove the platform end to end on a fresh clone —
copy its structure (`fetch.py` / `scraper.py` / `db.py` / `assets.py` /
`exporter.py`) as a starting point for a real bundle.

## Operate

```bash
harbor bundle run demo     # materialize the demo assets (scrape + upsert)
harbor bundle view demo    # render the HTML report
harbor agent-protocol summary demo
```

## Env

None required. `DEMO_SITE_URL` overrides the fixture URL (default
`http://demo_site`, the compose service hostname).
