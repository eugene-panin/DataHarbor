# Security Policy

## Supported versions

DataHarbor ships from a single rolling `main` branch (no long-term support
branches yet). Security fixes land on `main`; there is no backport policy
until the project has tagged, supported releases.

## Reporting a vulnerability

**Do not open a public GitHub issue for a security report.**

Report privately via **[GitHub Security Advisories](https://github.com/eugene-panin/DataHarbor/security/advisories/new)**
(repo → *Security* tab → *Report a vulnerability*). This opens a private
channel between you and the maintainer, with no other setup needed.

Please include:

- Affected component (`apps/`, a specific bundle, an extractor, `docker-compose.yml`, …)
- Steps to reproduce, or a proof of concept
- Impact you'd expect (data exposure, RCE, privilege escalation, etc.)

You should get an initial response within a few days. Once a fix is ready,
we'll coordinate disclosure timing with you before it's made public.

## Scope notes specific to this project

- `harbor bundle install <source>` clones and then **imports and executes**
  the bundle's Python. That is expected (bundles are code, like packages),
  not itself a vulnerability — but report it if you find a way to trigger
  that execution without the user explicitly running `install`.
- `.env` / `.env.example` ship **local development defaults only**
  (`ADMIN_PASSWORD=admin123`, etc.). Shipping better local defaults is a
  welcome PR; it is not a reportable vulnerability on its own — the real
  issue would be those defaults surviving into a non-local deployment,
  which is on the deployer, not the default.
- Please don't run automated scanners against the public demo fixtures or
  any hosted instance you don't own — the `demo_site` compose service is a
  static local fixture with nothing to find.
