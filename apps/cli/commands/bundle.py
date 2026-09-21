"""Bundle management commands."""
from __future__ import annotations

import base64
import logging
import os
import subprocess

import typer

from apps.bundle.distributor import BundleDistributor
from apps.bundle.paths import BUNDLES_DIR
from apps.bundle.plugin_contract import BundleContractError, load_manifest, resolve_dagster_entrypoint
from apps.bundle.validator import validate_all_bundles
from apps.cli.commands.platform import check_active_runtime
from apps.cli.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

app = typer.Typer(help="Manage modular business domain bundles", no_args_is_help=True)


def _refresh_dagster_workspace() -> None:
    """Best-effort regenerate Dagster multi-location workspace.yaml."""
    try:
        from apps.dagster_app.workspace_builder import (
            location_names,
            write_workspace_yaml,
        )

        path, doc, warnings = write_workspace_yaml(project_root=PROJECT_ROOT)
        names = location_names(doc)
        print(f"🗂️  Dagster workspace refreshed ({len(names)} locations): {path}")
        for w in warnings[:5]:
            print(f"   ⚠️  {w}")
    except Exception as e:
        logger.debug("workspace refresh skipped: %s", e)
        print(f"⚠️  Dagster workspace refresh skipped: {e}")


def _render_bundle_snapshot(bundle_name: str, runtime: str = "auto") -> str:
    selected_runtime = runtime
    if selected_runtime == "auto":
        active_runtime = check_active_runtime()
        if active_runtime == "DOCKER_COMPOSE":
            selected_runtime = "compose"
        elif active_runtime == "KUBERNETES":
            raise RuntimeError(
                "Kubernetes is active, but no exporter port-forward is configured. "
                "Use --runtime host only after exposing the cluster data services."
            )
        else:
            selected_runtime = "host"

    if selected_runtime == "host":
        return BundleDistributor().render_bundle_exporter(bundle_name)

    if selected_runtime != "compose":
        raise ValueError(f"Unsupported exporter runtime: {selected_runtime}")

    marker = "__DATAHARBOR_EXPORT_BASE64__:"
    script = (
        "import base64\n"
        "from apps.bundle.distributor import BundleDistributor\n"
        f"html = BundleDistributor().render_bundle_exporter({bundle_name!r})\n"
        f"print({marker!r} + base64.b64encode(html.encode('utf-8')).decode('ascii'))\n"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", "dataharbor_dagster", "python", "-c", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Docker exporter failed: {details[-2000:]}")

    encoded = next(
        (
            line[len(marker) :]
            for line in reversed(result.stdout.splitlines())
            if line.startswith(marker)
        ),
        None,
    )
    if not encoded:
        raise RuntimeError("Docker exporter returned no HTML payload")
    return base64.b64decode(encoded).decode("utf-8")


@app.command("list")
def list_bundles() -> None:
    """List all installed bundles and versions."""
    print("\n📦 INSTALLED DATAHARBOR BUNDLES:")
    print("=" * 60)
    bundles = BundleDistributor().list_bundles()
    if not bundles:
        print("No bundles currently installed.")
        print("Use 'harbor bundle install <src>' to add a bundle.\n")
        return
    for b in bundles:
        print(f"• {b['name']:<24} (v{b['version']}) — {b['description']}")
    print("=" * 60 + "\n")


@app.command("validate")
def validate_bundles() -> None:
    """Validate manifest schema and syntax integrity of all bundles."""
    print("\n📦 VALIDATING DATAHARBOR BUNDLES:")
    print("=" * 60)
    results = validate_all_bundles(os.path.join(PROJECT_ROOT, "bundles"))
    if not results:
        print("ℹ️  No bundles installed under bundles/ (open-core ships none).")
        print("    Install with: harbor bundle install <git-url>")
        print("=" * 60 + "\n")
        return
    failed = False
    for name, (is_valid, errors) in sorted(results.items()):
        symbol = "✅" if is_valid else "❌"
        print(f"{symbol} {name}")
        if not is_valid:
            failed = True
            for err in errors:
                print(f"    - {err}")
    print("=" * 60 + "\n")
    if failed:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_bundle_cmd(
    name: str | None = typer.Argument(
        None,
        help="Bundle name (default: diagnose all installed bundles)",
    ),
) -> None:
    """Diagnose engines, python deps, env vars, extractors, and Dagster entrypoint."""
    from apps.bundle.doctor import doctor_all_bundles, doctor_bundle, format_doctor_report

    print("\n🩺 DATAHARBOR BUNDLE DOCTOR")
    print("=" * 60)
    try:
        if name:
            reports = [doctor_bundle(name, bundles_dir=os.path.join(PROJECT_ROOT, "bundles"))]
        else:
            reports = doctor_all_bundles(bundles_dir=os.path.join(PROJECT_ROOT, "bundles"))
    except FileNotFoundError as e:
        print(f"❌ {e}\n")
        raise typer.Exit(code=1) from e

    if not reports:
        print("No installable bundles found under bundles/.")
        print("Use 'harbor bundle new <name>' or 'harbor bundle install <src>'.\n")
        return

    failed = False
    for report in reports:
        print(format_doctor_report(report))
        print("-" * 60)
        if not report.ok:
            failed = True
    print("=" * 60 + "\n")
    if failed:
        raise typer.Exit(code=1)


@app.command("templates")
def list_templates_cmd() -> None:
    """List available bundle scaffold templates."""
    from apps.bundle.scaffold import list_bundle_templates

    print("\n📦 BUNDLE SCAFFOLD TEMPLATES:")
    print("=" * 60)
    for tpl in list_bundle_templates():
        print(f"• {tpl.id:<10} — {tpl.title}")
        print(f"  {tpl.description}")
        print(f"  files: {', '.join(tpl.files)}")
    print("=" * 60)
    print("Usage: harbor bundle new <name> --template ml\n")


@app.command("new")
def new_bundle(
    name: str = typer.Argument(..., help="Bundle name (Python identifier)"),
    template: str = typer.Option(
        "default",
        "--template",
        "-t",
        help="Scaffold template: default | ml | etl | dagster | catalog",
    ),
    description: str | None = typer.Option(None, "--description"),
    category: str = typer.Option("custom", "--category"),
    extractors: str | None = typer.Option(
        None, "--extractors", help="Comma-separated extractor ids/URLs"
    ),
    path: str | None = typer.Option(
        None, "--path", help="Target directory (default: bundles/<name>)"
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing path"),
) -> None:
    """Scaffold a new bundle from a template."""
    from apps.bundle.scaffold import create_bundle

    extractor_list = [x.strip() for x in (extractors or "").split(",") if x.strip()]
    print(f"\n📦 Creating bundle scaffold '{name}' (template: {template})...")
    try:
        result = create_bundle(
            name,
            template=template,
            description=description,
            category=category,
            extractors=extractor_list,
            target_dir=path,
            force=force,
        )
    except ValueError as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ {result['message']}")
    print(f"   Template: {result['template']}")
    print(f"   Files: {', '.join(result['files'])}")
    print("   Next: fill assets.py `defs`, then `harbor bundle doctor <name>` / `validate`")
    _refresh_dagster_workspace()
    print()


@app.command("install")
def install_bundle(
    source: str = typer.Argument(..., help="Git URL, archive, or folder path"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing bundle"),
) -> None:
    """Install bundle and auto-resolve extractors from its manifest."""
    print(f"\n📦 Installing DataHarbor Bundle from: {source}...")
    try:
        dest = BundleDistributor().install_bundle(source, force=force)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Successfully installed bundle to: {dest.get('installed_path', dest)}")
    for item in dest.get("extractors") or []:
        src = f" <- {item['source']}" if item.get("source") else ""
        print(f"   🔌 extractor [{item['status']}]: {item['name']}{src}")
    from apps.bundle.env_requirements import hint_for_bundle_path

    hint = hint_for_bundle_path(str(dest.get("installed_path") or ""))
    if hint:
        print(hint)
    _refresh_dagster_workspace()
    print()


@app.command("resolve")
def resolve_extractors(
    bundle_name: str = typer.Argument(..., help="Installed bundle name"),
    force: bool = typer.Option(False, "--force", help="Reinstall extractors"),
) -> None:
    """Install/update extractors declared by an installed bundle."""
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
def pack_bundle(
    bundle_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output", help="Output directory"),
) -> None:
    """Pack bundle into a clean .tar.gz archive."""
    print(f"\n📦 Packing DataHarbor Bundle: '{bundle_name}'...")
    try:
        archive_path = BundleDistributor().pack_bundle(bundle_name, output_dir=output)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Successfully packed bundle archive: {archive_path}\n")


@app.command("remove")
def remove_bundle(bundle_name: str = typer.Argument(...)) -> None:
    """Remove an installed bundle directory."""
    print(f"\n🗑️ Removing DataHarbor Bundle: '{bundle_name}'...")
    try:
        BundleDistributor().remove_bundle(bundle_name)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    print(f"✨ Bundle '{bundle_name}' successfully removed.")
    _refresh_dagster_workspace()
    print()


@app.command("publish")
def publish_bundle(
    name: str = typer.Argument(..., help="Bundle directory name under bundles/"),
    remote: str | None = typer.Option(
        None, "--remote", help="Existing git remote URL (skips gh repo create)"
    ),
    workdir: str | None = typer.Option(
        None,
        "--workdir",
        help="Permanent staging directory (default: temporary snapshot)",
    ),
    repo_name: str | None = typer.Option(
        None, "--repo-name", help="GitHub repo name (default: dh-bundle-<name>)"
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
    allow_local_extractors: bool = typer.Option(
        False,
        "--allow-local-extractors",
        help="Allow publish even if requirements.extractors still use local ids/paths",
    ),
) -> None:
    """Publish bundle to a git repo (temp staging; gh optional)."""
    from apps.cli.publish import publish_plugin

    resolved_visibility = "public" if public else visibility
    print(f"\n📦 Publishing bundle '{name}' ({resolved_visibility})...")
    try:
        result = publish_plugin(
            "bundle",
            name,
            remote=remote,
            workdir=workdir,
            repo_name=repo_name,
            visibility=resolved_visibility,
            dry_run=dry_run,
            allow_local_extractors=allow_local_extractors,
        )
    except ValueError as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        print(f"❌ Publish failed: {e}")
        raise typer.Exit(code=1) from e

    unpublished = result.get("unpublished_extractors") or []
    if unpublished:
        print("\n⚠️  Local extractors are not published as git remotes yet:")
        for item in unpublished:
            print(f"   • {item['name']} — {item['reason']}")
            print(f"       → {item['suggest']}")
        print(
            "   Platform will not auto-publish them. Publish extractors first, "
            "then put git URLs into requirements.extractors.\n"
        )

    if result.get("status") == "dry_run":
        print("✨ Dry-run OK — no remote changes made.")
        print(f"   source : {result['source']}")
        print(f"   repo   : {result['repo_name']} ({result['visibility']})")
        print(f"   mode   : {result['mode']}")
        if result.get("remote"):
            print(f"   remote : {result['remote']}")
        if result.get("install_hint"):
            print(f"   next   : {result['install_hint']}")
        if unpublished and not allow_local_extractors:
            print(
                "   note   : real publish will stop until extractors are published "
                "(or pass --allow-local-extractors)"
            )
        print()
        return

    print(f"✨ {result['message']}")
    if result.get("staging"):
        print(f"   workdir: {result['staging']}")
    print(f"   install: {result['install_hint']}\n")


@app.command("run")
def run_bundle(
    bundle_name: str = typer.Argument(...),
    runtime: str = typer.Option("auto", "--runtime", help="auto|host|compose"),
) -> None:
    """Materialize every Dagster asset for a bundle synchronously (no UI needed)."""
    selected_runtime = runtime
    if selected_runtime == "auto":
        active_runtime = check_active_runtime()
        if active_runtime == "KUBERNETES":
            print(
                "❌ Kubernetes is active. Use `dagster asset materialize` directly, "
                "or the Dagster UI, after port-forwarding the cluster."
            )
            raise typer.Exit(code=1)
        selected_runtime = "compose" if active_runtime == "DOCKER_COMPOSE" else "host"

    bundle_path = os.path.join(BUNDLES_DIR, bundle_name)
    try:
        manifest = load_manifest(bundle_path)
        module_leaf, attr = resolve_dagster_entrypoint(manifest)
    except (OSError, BundleContractError) as e:
        print(f"❌ Cannot resolve Dagster entrypoint for bundle '{bundle_name}': {e}")
        raise typer.Exit(code=1) from e

    print(f"\n🚀 Materializing assets for bundle '{bundle_name}' ({selected_runtime})...")
    dagster_cmd = [
        "dagster",
        "asset",
        "materialize",
        "-m",
        f"bundles.{bundle_name}.{module_leaf}",
        "-a",
        attr,
        "--select",
        "*",
    ]

    if selected_runtime == "compose":
        result = subprocess.run(["docker", "exec", "-i", "dataharbor_dagster", *dagster_cmd])
    elif selected_runtime == "host":
        result = subprocess.run(dagster_cmd, cwd=PROJECT_ROOT)
    else:
        print(f"❌ Unsupported runtime: {selected_runtime}")
        raise typer.Exit(code=1)

    if result.returncode != 0:
        print(f"❌ Bundle '{bundle_name}' run failed (exit {result.returncode}).\n")
        raise typer.Exit(code=1)
    print(f"✨ Bundle '{bundle_name}' materialized. Try: harbor bundle view {bundle_name}\n")


@app.command("export")
def export_bundle(
    bundle_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output"),
    runtime: str = typer.Option("auto", "--runtime", help="auto|host|compose"),
) -> None:
    """Export standalone interactive HTML presentation report."""
    print(f"\n🎨 Rendering Presentation Layer for Bundle: '{bundle_name}'...")
    try:
        html_content = _render_bundle_snapshot(bundle_name, runtime=runtime)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e
    out_path = output or os.path.join(PROJECT_ROOT, "exports", f"{bundle_name}_dossier.html")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    os.chmod(out_path, 0o600)
    print(f"✨ Interactive Bundle Presentation View saved to: {out_path}\n")


@app.command("view")
def view_bundle(
    bundle_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output"),
    serve: bool = typer.Option(False, "--serve", help="Launch dynamic web server"),
    port: int = typer.Option(8090, "--port"),
    runtime: str = typer.Option("auto", "--runtime", help="auto|host|compose"),
) -> None:
    """View or serve interactive presentation dossier."""
    if not serve:
        export_bundle(bundle_name, output=output, runtime=runtime)
        return

    print(f"\n🎨 Preparing Dynamic Presentation View Server for Bundle: '{bundle_name}'...")
    import http.server
    import socketserver

    try:
        _render_bundle_snapshot(bundle_name, runtime=runtime)
    except Exception as e:
        print(f"❌ {e}")
        raise typer.Exit(code=1) from e

    class PresentationHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if self.path not in ("/", "/index.html"):
                self.send_error(404)
                return
            try:
                dynamic_html = _render_bundle_snapshot(bundle_name, runtime=runtime)
                encoded = dynamic_html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.send_header("Content-length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(encoded)
            except Exception as e:
                logger.error(f"Error serving bundle presentation view: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"500 Internal Server Error: {e}".encode())

    print(f"🚀 Serving interactive Bundle Presentation View at: http://localhost:{port}")
    print("Press Ctrl+C to stop web server.\n")
    try:
        with socketserver.TCPServer(("127.0.0.1", port), PresentationHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped Bundle View server.")
