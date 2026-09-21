# Changelog

## 2026-09-21 — Audit remediation

An external review audited the platform after the initial public release and
flagged 22 findings (F01–F22) plus 4 additional observations. All of them
were verified against this codebase — several by live reproduction against a
running Postgres/ClickHouse/Qdrant/SeaweedFS/Dagster stack or a throwaway
`kind` cluster, not just code review — and fixed. Grouped by area below;
each links to the commit with the full root-cause writeup and how it was
verified.

### Kubernetes / Tilt

- **F12** — The K8s/Tilt deployment was broken end to end and had apparently
  never actually been deployed: the Dagster image name didn't match what
  Tilt builds, the ConfigMap's `POSTGRES_HOST` didn't match the Postgres
  Service name, SeaweedFS and Dagster had no persistent volumes (data/run
  history lost on every pod restart), `demo_site` and Grafana didn't exist
  in the K8s manifests at all, the `local-with-n8n` overlay failed to build
  under kustomize's security restrictor, and the n8n manifest hardcoded a
  bcrypt password hash that didn't match any known password.
  [`26d68d1`](https://github.com/eugene-panin/DataHarbor/commit/26d68d1)

### Platform / CLI

- **F13** — `.env.example` pointed ClickHouse/Qdrant/S3 at Docker-internal
  DNS names unreachable from the host CLI; `harbor down` picked `tilt` or
  Compose based on which binary was installed rather than which runtime was
  actually running, so it could silently no-op instead of stopping the real
  stack.
  [`80525ee`](https://github.com/eugene-panin/DataHarbor/commit/80525ee)
- **F17** — Six validation/routing gaps: a non-string extractor `entrypoint`
  passed validation, relative imports broke extractor validation only (not
  real runtime), domain matching used loose substrings, the extractor
  registry cache didn't actually invalidate reinstalled code, an empty
  `--only` bundle filter silently meant "all bundles", and `bundle run`
  ignored the manifest's declared Dagster entrypoint.
  [`193433d`](https://github.com/eugene-panin/DataHarbor/commit/193433d)
- **F20** — Every local dev service (Postgres, Dagster, SeaweedFS, ClickHouse,
  Qdrant, the demo site) published on `0.0.0.0` instead of loopback, and
  Qdrant never enforced the API key the app was configured to send it.
  [`4a790e0`](https://github.com/eugene-panin/DataHarbor/commit/4a790e0)
- **F19** — The health check re-scanned the same old stdout error on every
  run instead of tracking a cursor, generating false repeat alerts.
  [`e153040`](https://github.com/eugene-panin/DataHarbor/commit/e153040)
- **F10** — Installing a bundle/extractor via a git URL derived its identity
  from the repo URL instead of its own manifest, so publish → install could
  round-trip to a different name.
  [`ad6e81c`](https://github.com/eugene-panin/DataHarbor/commit/ad6e81c)
- **F08 / F09** — `--dry-run` on publish could still delete and rebuild the
  target workdir; a failed `--force` install could destroy a working plugin
  with nothing left in its place.
  [`a9cae65`](https://github.com/eugene-panin/DataHarbor/commit/a9cae65)
- **F01 / F02 / F04** — A scraper failing every single run for 24h could
  still report `HEALTHY`; a read-only health summary had a side effect it
  shouldn't have; a related status-computation gap.
  [`bf6fde9`](https://github.com/eugene-panin/DataHarbor/commit/bf6fde9)

### Data layer

- **F14** — `QdrantClient.search()` was removed upstream (the pinned client
  version has no `search` attribute), so every vector search silently
  raised and returned empty results; ClickHouse, once marked unavailable
  after one transient failure, stayed "down" forever with no retry.
  [`f4ceff3`](https://github.com/eugene-panin/DataHarbor/commit/f4ceff3)
- **F06** — Backup/restore could silently succeed on failure and, in one
  path, corrupt the data it claimed to have saved — found by running it
  against a real Postgres instance with real messy/Unicode scraped data.
  [`2e4efce`](https://github.com/eugene-panin/DataHarbor/commit/2e4efce)
- **F15** — The published wheel shipped no `manifest.json`/`.yaml`/`.xml`
  files — `packages.find` only pulls in `.py` files without
  `package-data`, so every extractor and bundle was undiscoverable after a
  real `pip install`, only ever having been exercised from a git checkout.
  [`5d4d8bf`](https://github.com/eugene-panin/DataHarbor/commit/5d4d8bf)

### Self-healing / AI remediation

- **F03 / F05** — Rollback after a failed retry didn't cover every exit
  path (an LLM failure on attempt 2 could leave attempt 1's bad patch on
  disk); the remediator was extractor-unaware and could patch the wrong
  file. Found by an external review of this session's own prior fix and
  reproduced live against the demo stack before patching.
  [`3dd9b5c`](https://github.com/eugene-panin/DataHarbor/commit/3dd9b5c)
- **F16 / F21** — A failed demo pipeline run looked identical to a
  successful one in the Dagster UI; `use_proxy=False` didn't actually
  disable a proxy already set via the environment.
  [`f758155`](https://github.com/eugene-panin/DataHarbor/commit/f758155)
- **F18** — LLM provider/key selection wasn't tied to the chosen provider —
  the first non-empty API key across *any* configured provider could be
  used regardless of `AI_REPAIR_PROVIDER`, and the model name had the same
  problem in reverse.
  [`cacd582`](https://github.com/eugene-panin/DataHarbor/commit/cacd582)
- **F22** — The optional embeddings helper zero-padded real 384-dim vectors
  to a fake "512-dimensional" shape and reloaded its model on every call;
  the ad-creative generator's docstring overclaimed LLM-driven analysis for
  what is a fixed template.
  [`b83b838`](https://github.com/eugene-panin/DataHarbor/commit/b83b838)

### Security

- **F07 / F11** — Three unguarded `tar.extractall()` calls in
  backup/restore and one in the extractor distributor allowed path
  traversal (zip-slip/tar-slip) on install/restore; secrets could leak
  into Docker build layers.
  [`5114fc8`](https://github.com/eugene-panin/DataHarbor/commit/5114fc8)
- **Publish followed symlinks** — `harbor bundle/extractor publish` copied
  plugin source with `shutil.copytree`'s default `symlinks=False`, which
  *dereferences* symlinks — a symlink anywhere in a plugin's source tree
  pointing outside it could have its real target's content copied into a
  snapshot pushed to a public git repo. Verified live with a symlinked
  file and directory pointing at secret content outside the source tree.
  [`4bad107`](https://github.com/eugene-panin/DataHarbor/commit/4bad107)
- **`uninstall.sh` lied about backup success** — `harbor backup create ||
  true` swallowed any backup failure (including "no harbor CLI found at
  all") and the script printed "successfully preserved" unconditionally
  before deleting the install. Now aborts (or asks for confirmation
  interactively) instead of destroying an unbacked-up install.
  [`4bad107`](https://github.com/eugene-panin/DataHarbor/commit/4bad107)

### Other correctness

- **S3 helper wasn't actually streaming** — `download_media_stream_to_s3`
  buffered an entire remote media file into memory before uploading it,
  despite being named and documented as streaming. Now uses
  `upload_fileobj`, verified live end to end against SeaweedFS.
  [`4bad107`](https://github.com/eugene-panin/DataHarbor/commit/4bad107)
- **Scraper double-execution risk** — the AI remediator's verification
  step retried a scrape call `except TypeError`, which could catch a bug
  *inside* the scraper (after it already made real requests or writes) and
  silently run it a second time. `inspect.signature` now decides the
  calling convention up front instead of guessing and retrying.
  [`4bad107`](https://github.com/eugene-panin/DataHarbor/commit/4bad107)
