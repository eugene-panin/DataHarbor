"""Dagster workspace commands (named profiles + multi code location)."""
from __future__ import annotations

import os

import typer

from apps.cli.paths import PROJECT_ROOT
from apps.dagster_app.workspace_builder import (
    DEFAULT_WORKSPACE_PATH,
    PROFILES_PATH,
    WORKSPACES_DIR,
    load_workspace_profiles,
    location_names,
    workspace_path_for_name,
    write_named_workspace,
    write_workspace_yaml,
)

app = typer.Typer(help="Dagster workspace (named profiles / multi code location)", no_args_is_help=True)


def _parse_only(only: str) -> list[str] | None:
    text = (only or "").strip()
    if not text:
        return None
    return [p.strip() for p in text.split(",") if p.strip()]


@app.command("refresh")
def refresh_workspace(
    name: str = typer.Option(
        "",
        "--name",
        "-n",
        help="Named profile from workspace_profiles.yaml (e.g. store_intel). Default: all → workspace.yaml",
    ),
    only: str = typer.Option(
        "",
        "--only",
        help="Comma-separated bundle ids (overrides profile bundles). Implies --name if set alone as filter with --path",
    ),
    path: str = typer.Option(
        "",
        "--path",
        help="Explicit output yaml path (default: workspace.yaml or workspaces/<name>.yaml)",
    ),
    no_core: bool = typer.Option(
        False,
        "--no-core",
        help="Omit the core code location",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail if any selected bundle is invalid (default: skip invalid)",
    ),
) -> None:
    """Regenerate a Dagster workspace: core + selected bundle locations."""
    profile = (name or "").strip() or "all"
    only_list = _parse_only(only)

    if path:
        out = path
        include = only_list
        if include is None and profile != "all":
            from apps.dagster_app.workspace_builder import resolve_profile_bundles

            include, _ = resolve_profile_bundles(profile)
        print(f"\n🗂️  Refreshing Dagster workspace → {out}")
        print("=" * 60)
        try:
            written, doc, warnings = write_workspace_yaml(
                out,
                project_root=PROJECT_ROOT,
                skip_invalid=not strict,
                include_bundles=include,
                include_core=not no_core,
                profile_name=profile if profile != "all" else None,
            )
        except Exception as e:
            print(f"❌ {e}\n")
            raise typer.Exit(code=1) from e
    else:
        print(f"\n🗂️  Refreshing Dagster workspace profile '{profile}'...")
        print("=" * 60)
        try:
            written, doc, warnings = write_named_workspace(
                profile,
                only=only_list,
                include_core=not no_core,
                skip_invalid=not strict,
                project_root=PROJECT_ROOT,
            )
        except KeyError as e:
            print(f"❌ {e}\n")
            raise typer.Exit(code=1) from e
        except Exception as e:
            print(f"❌ {e}\n")
            raise typer.Exit(code=1) from e

    names = location_names(doc)
    print(f"✨ Wrote {written}")
    print(f"📍 Locations ({len(names)}): {', '.join(names)}")
    for w in warnings:
        print(f"⚠️  {w}")
    active_profile = profile if profile != "all" else "all"
    print(f"💡 Run with: DAGSTER_WORKSPACE_NAME={active_profile} python -m apps.dagster_app.run_dev")
    print("🌐 UI: http://localhost:3000")
    print("=" * 60 + "\n")


@app.command("list")
def list_workspaces() -> None:
    """List named profiles and generated workspace files."""
    print("\n🗂️  Workspace profiles:")
    print("=" * 60)
    try:
        doc = load_workspace_profiles()
    except Exception as e:
        print(f"❌ {e}\n")
        raise typer.Exit(code=1) from e

    for pname, profile in sorted((doc.get("profiles") or {}).items()):
        bundles = (profile or {}).get("bundles", "*")
        desc = (profile or {}).get("description") or ""
        out = workspace_path_for_name(pname)
        exists = "✓" if os.path.isfile(out) else "·"
        print(f"{exists} {pname}")
        if desc:
            print(f"    {desc}")
        print(f"    bundles={bundles}")
        print(f"    file={out}")
    print(f"\nProfiles file: {PROFILES_PATH}")
    print(f"Generated dir: {WORKSPACES_DIR}")
    print("=" * 60 + "\n")


@app.command("show")
def show_workspace(
    name: str = typer.Option(
        "",
        "--name",
        "-n",
        help="Profile name (default: all → workspace.yaml)",
    ),
    path: str = typer.Option(
        "",
        "--path",
        help="Explicit workspace.yaml path",
    ),
) -> None:
    """Print configured code location names from a workspace file."""
    if path:
        target = path
    elif name:
        target = workspace_path_for_name(name.strip())
    else:
        target = DEFAULT_WORKSPACE_PATH

    if not os.path.isfile(target):
        print(f"❌ Workspace file not found: {target}")
        hint = f"harbor workspace refresh --name {name}" if name else "harbor workspace refresh"
        print(f"Run: {hint}\n")
        raise typer.Exit(code=1)

    import yaml

    with open(target, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    names = location_names(doc)
    print(f"\n🗂️  Dagster code locations ({target}):")
    print("=" * 60)
    for loc in names:
        print(f"• {loc}")
    if not names:
        print("(empty)")
    print("=" * 60 + "\n")
