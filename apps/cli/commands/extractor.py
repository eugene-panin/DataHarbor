"""Extractor management commands."""
from __future__ import annotations

import os

import typer

from apps.cli.paths import PROJECT_ROOT
from bundles.distributor import BundleDistributor
from extractors.distributor import ExtractorDistributor
from extractors.validator import validate_all_extractors

app = typer.Typer(help="Manage separately distributed resource extractors", no_args_is_help=True)


@app.command("list")
def list_extractors() -> None:
    """List all installed extractors and versions."""
    print("\n🔌 INSTALLED DATAHARBOR EXTRACTORS:")
    print("=" * 60)
    extractors = ExtractorDistributor().list_extractors()
    if not extractors:
        print("No extractors currently installed.")
        print("Use 'harbor extractor install <src>' to add an extractor.\n")
        return
    for ext in extractors:
        domains = ", ".join(ext.get("domains") or []) or "n/a"
        status = "OK" if ext.get("is_valid") else "INVALID"
        print(f"• {ext['name']:<16} (v{ext['version']}) [{status}] domains={domains}")
        print(f"  {ext['description']}")
    print("=" * 60 + "\n")


@app.command("validate")
def validate_extractors() -> None:
    """Validate manifest schema and parse entrypoints."""
    print("\n🔌 VALIDATING DATAHARBOR EXTRACTORS:")
    print("=" * 60)
    results = validate_all_extractors(os.path.join(PROJECT_ROOT, "extractors"))
    if not results:
        print("No extractors found.\n")
        return
    failed = False
    for name, (is_valid, errors) in results.items():
        symbol = "✅" if is_valid else "❌"
        print(f"{symbol} {name}")
        if not is_valid:
            failed = True
            for err in errors:
                print(f"    - {err}")
    print("=" * 60 + "\n")
    if failed:
        raise typer.Exit(code=1)


@app.command("new")
def new_extractor(
    name: str = typer.Argument(..., help="Extractor name (Python identifier)"),
    description: str | None = typer.Option(None, "--description"),
    domains: str | None = typer.Option(
        None, "--domains", help="Comma-separated domains, e.g. linkedin.com"
    ),
    path: str | None = typer.Option(
        None, "--path", help="Target directory (default: extractors/<name>)"
    ),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Scaffold a new resource extractor."""
    from extractors.scaffold import create_extractor

    domain_list = [x.strip() for x in (domains or "").split(",") if x.strip()]
    print(f"\n🔌 Creating extractor scaffold '{name}'...")
    try:
        result = create_extractor(
            name,
            description=description,
            domains=domain_list or None,
            target_dir=path,
            force=force,
        )
    except ValueError as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ {result['message']}")
    print(f"   Files: {', '.join(result['files'])}")
    print("   Next: implement parse() selectors, then `harbor extractor validate`\n")


@app.command("install")
def install_extractor(
    source: str = typer.Argument(..., help="Git URL, archive, or folder path"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Install extractor from Git URL, archive, or folder."""
    print(f"\n🔌 Installing DataHarbor Extractor from: {source}...")
    try:
        dest = ExtractorDistributor().install_extractor(source, force=force)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Successfully installed extractor to: {dest}\n")


@app.command("resolve")
def resolve_for_bundle(
    bundle_name: str = typer.Argument(..., help="Installed bundle name"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Install extractors declared in an installed bundle manifest."""
    print(f"\n🔌 Resolving extractors for bundle '{bundle_name}'...")
    try:
        report = BundleDistributor().resolve_extractors(bundle_name, force=force)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    if not report:
        print("No extractors declared in bundle manifest.\n")
        return
    for item in report:
        src = f" <- {item['source']}" if item.get("source") else ""
        print(f"• [{item['status']}] {item['name']}{src}")
    print()


@app.command("pack")
def pack_extractor(
    extractor_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    """Pack extractor into a clean .tar.gz archive."""
    print(f"\n🔌 Packing DataHarbor Extractor: '{extractor_name}'...")
    try:
        archive_path = ExtractorDistributor().pack_extractor(
            extractor_name, output_dir=output
        )
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Successfully packed extractor archive: {archive_path}\n")


@app.command("remove")
def remove_extractor(extractor_name: str = typer.Argument(...)) -> None:
    """Remove an installed extractor directory."""
    print(f"\n🗑️ Removing DataHarbor Extractor: '{extractor_name}'...")
    try:
        ExtractorDistributor().remove_extractor(extractor_name)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Extractor '{extractor_name}' successfully removed.\n")


@app.command("publish")
def publish_extractor(
    name: str = typer.Argument(..., help="Extractor directory name under extractors/"),
    remote: str | None = typer.Option(
        None, "--remote", help="Existing git remote URL (skips gh repo create)"
    ),
    workdir: str | None = typer.Option(
        None,
        "--workdir",
        help="Permanent staging directory (default: temporary snapshot)",
    ),
    repo_name: str | None = typer.Option(
        None, "--repo-name", help="GitHub repo name (default: dh-extractor-<name>)"
    ),
    visibility: str = typer.Option(
        "private",
        "--visibility",
        help="GitHub repo visibility: private (default) or public",
    ),
    public: bool = typer.Option(
        False,
        "--public",
        help="Shortcut for --visibility public",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and plan without pushing"),
) -> None:
    """Publish extractor to a git repo (temp staging; gh optional)."""
    from apps.cli.publish import publish_plugin

    resolved_visibility = "public" if public else visibility
    print(f"\n🔌 Publishing extractor '{name}' ({resolved_visibility})...")
    try:
        result = publish_plugin(
            "extractor",
            name,
            remote=remote,
            workdir=workdir,
            repo_name=repo_name,
            visibility=resolved_visibility,
            dry_run=dry_run,
        )
    except ValueError as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        raise typer.Exit(code=1) from e

    if result.get("status") == "dry_run":
        print("✨ Dry-run OK — no remote changes made.")
        print(f"   source : {result['source']}")
        print(f"   repo   : {result['repo_name']} ({result['visibility']})")
        print(f"   mode   : {result['mode']}")
        if result.get("remote"):
            print(f"   remote : {result['remote']}")
        if result.get("install_hint"):
            print(f"   next   : {result['install_hint']}")
        print()
        return

    print(f"✨ {result['message']}")
    if result.get("staging"):
        print(f"   workdir: {result['staging']}")
    print(f"   install: {result['install_hint']}\n")
