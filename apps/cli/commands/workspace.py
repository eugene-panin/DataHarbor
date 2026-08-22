"""Dagster workspace commands (multi code location)."""
from __future__ import annotations

import os

import typer

from apps.cli.paths import PROJECT_ROOT
from apps.dagster_app.workspace_builder import location_names, write_workspace_yaml

app = typer.Typer(help="Dagster workspace (multi code location)", no_args_is_help=True)


@app.command("refresh")
def refresh_workspace(
    path: str = typer.Option(
        "",
        "--path",
        help="Output workspace.yaml path (default: apps/dagster_app/workspace.yaml)",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail if any bundle is invalid (default: skip invalid, keep generating)",
    ),
) -> None:
    """Regenerate workspace.yaml: core + one location per bundle."""
    out = path or os.path.join(PROJECT_ROOT, "apps", "dagster_app", "workspace.yaml")
    print("\n🗂️  Refreshing Dagster workspace (multi code location)...")
    print("=" * 60)
    try:
        written, doc, warnings = write_workspace_yaml(
            out,
            project_root=PROJECT_ROOT,
            skip_invalid=not strict,
        )
    except Exception as e:
        print(f"❌ {e}\n")
        raise typer.Exit(code=1) from e

    names = location_names(doc)
    print(f"✨ Wrote {written}")
    print(f"📍 Locations ({len(names)}): {', '.join(names)}")
    for w in warnings:
        print(f"⚠️  {w}")
    print("=" * 60 + "\n")


@app.command("show")
def show_workspace(
    path: str = typer.Option(
        "",
        "--path",
        help="workspace.yaml path (default: apps/dagster_app/workspace.yaml)",
    ),
) -> None:
    """Print configured code location names from workspace.yaml."""
    target = path or os.path.join(PROJECT_ROOT, "apps", "dagster_app", "workspace.yaml")
    if not os.path.isfile(target):
        print(f"❌ Workspace file not found: {target}")
        print("Run: harbor workspace refresh\n")
        raise typer.Exit(code=1)

    import yaml

    with open(target, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    names = location_names(doc)
    print("\n🗂️  Dagster code locations:")
    print("=" * 60)
    for name in names:
        print(f"• {name}")
    if not names:
        print("(empty)")
    print("=" * 60 + "\n")
