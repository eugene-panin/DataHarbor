"""Bundle-declared environment variables (manifest requirements.env).

Secrets stay in the repo-root ``.env``. Core never writes that file and never
ships keys inside a bundle git repo. Install prints the list; doctor checks
whether they are set.
"""
from __future__ import annotations

import os
import re
from typing import Any

ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class EnvRequirementError(ValueError):
    """Invalid ``requirements.env`` entry in a bundle manifest."""


def parse_env_requirements(raw: Any) -> list[dict[str, Any]]:
    """Normalize ``requirements.env`` to a list of spec dicts.

    Accepted items:
    * ``"FOO_API_KEY"`` — required, empty description
    * ``{"name": "FOO_API_KEY", "required": true, "description": "..."}``
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise EnvRequirementError("requirements.env must be an array")

    seen: set[str] = set()
    specs: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            name = item.strip()
            required = True
            description = ""
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            required = bool(item.get("required", True))
            description = str(item.get("description") or "").strip()
        else:
            raise EnvRequirementError(
                f"requirements.env[{index}] must be a string or object, got {type(item).__name__}"
            )
        if not name:
            raise EnvRequirementError(f"requirements.env[{index}] is missing 'name'")
        if not ENV_NAME_RE.match(name):
            raise EnvRequirementError(
                f"requirements.env[{index}] name {name!r} must match {ENV_NAME_RE.pattern}"
            )
        if name in seen:
            raise EnvRequirementError(f"requirements.env duplicates {name!r}")
        seen.add(name)
        specs.append({"name": name, "required": required, "description": description})
    return specs


def env_is_set(name: str, environ: dict[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return bool((source.get(name) or "").strip())


def check_env_requirements(
    specs: list[dict[str, Any]],
    *,
    environ: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return one status row per spec: ok | warn | fail."""
    rows: list[dict[str, Any]] = []
    for spec in specs:
        name = spec["name"]
        present = env_is_set(name, environ)
        if present:
            status = "ok"
            detail = f"{name} is set"
        elif spec["required"]:
            status = "fail"
            detail = f"{name} is required — add it to the repo-root .env"
        else:
            status = "warn"
            detail = f"{name} is optional and unset — related bundle jobs may skip"
        if spec.get("description") and status != "ok":
            detail = f"{detail} ({spec['description']})"
        rows.append({**spec, "status": status, "present": present, "detail": detail})
    return rows


def format_env_install_hint(
    specs: list[dict[str, Any]],
    *,
    environ: dict[str, str] | None = None,
) -> str:
    """Human-readable block for ``harbor bundle install``. Empty if nothing declared."""
    if not specs:
        return ""
    rows = check_env_requirements(specs, environ=environ)
    lines = [
        "🔑 This bundle expects variables in the repo-root .env (not in the bundle repo):",
    ]
    for row in rows:
        flag = "required" if row["required"] else "optional"
        state = "set" if row["present"] else "missing"
        desc = f"  — {row['description']}" if row.get("description") else ""
        lines.append(f"   • {row['name']}  [{flag}, {state}]{desc}")
    lines.append("   Add missing keys to .env, then run `harbor bundle doctor <name>`.")
    return "\n".join(lines)


def hint_for_bundle_path(bundle_path: str, *, environ: dict[str, str] | None = None) -> str:
    """Load manifest.json at ``bundle_path`` and format the install hint."""
    import json
    from pathlib import Path

    manifest_path = Path(bundle_path) / "manifest.json"
    if not manifest_path.is_file():
        return ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    raw = (manifest.get("requirements") or {}).get("env") if isinstance(manifest, dict) else None
    try:
        specs = parse_env_requirements(raw)
    except EnvRequirementError:
        return ""
    return format_env_install_hint(specs, environ=environ)
