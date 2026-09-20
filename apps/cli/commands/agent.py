"""Harbor Agent Protocol (HAP v1.0) commands."""
from __future__ import annotations

import json
import os

import typer

from apps.cli.paths import PROJECT_ROOT

app = typer.Typer(help="Harbor Agent Protocol (HAP v1.0) for external LLM agents", no_args_is_help=True)

_COMPACT = {"separators": (",", ":"), "default": str}


@app.command("status")
def status() -> None:
    """JSON health array: HEALTHY | DEGRADED | CRITICAL (not ZERO_ROWS)."""
    from apps.observability.health_checker import ScraperHealthChecker

    report = ScraperHealthChecker().check_all_scrapers_health()
    print(json.dumps(report, indent=2, default=str))


@app.command("summary")
def summary(
    bundle_name: str | None = typer.Argument(
        None,
        help="Bundle id. Omit for a fleet digest of all installed bundles.",
    ),
) -> None:
    """Compact operator digest: counts, SLA, issues, last log. No source code."""
    from apps.observability.health_checker import ScraperHealthChecker

    checker = ScraperHealthChecker()
    if bundle_name:
        payload = checker.summarize_bundle(bundle_name)
    else:
        payload = checker.summarize_all()
    print(json.dumps(payload, **_COMPACT))
    action = payload.get("action")
    if action in {"STOP", "REMEDIATE"} or payload.get("status") == "UNKNOWN":
        raise typer.Exit(code=1)


@app.command("diagnose")
def diagnose(bundle_name: str = typer.Argument(...)) -> None:
    """Compressed JSON from last scraper_execution_logs row + scraper snippet.

    Does not include live HTML or failing CSS selectors.
    """
    from apps.observability.ai_remediator import AIRemediatorEngine

    compressed_json = AIRemediatorEngine().get_compressed_diagnostic_json(bundle_name)
    print(json.dumps(compressed_json, indent=2, default=str))


@app.command("patch")
def patch(
    bundle_name: str = typer.Argument(...),
    code_file: str = typer.Option(..., "--code-file", help="Path to replacement Python code"),
) -> None:
    """AST-validate then replace the entire bundles/<name>/scraper.py."""
    from apps.observability.ai_remediator import AIRemediatorEngine

    scraper_path = os.path.join(PROJECT_ROOT, "bundles", bundle_name, "scraper.py")
    bundle_dir = os.path.dirname(scraper_path)
    if not os.path.isdir(bundle_dir):
        print(
            json.dumps(
                {"status": "FAILED", "error": f"Bundle '{bundle_name}' not found under bundles/."},
                indent=2,
            )
        )
        raise typer.Exit(code=1)

    with open(code_file, encoding="utf-8") as f:
        patch_code = f.read()
    remediator = AIRemediatorEngine()
    is_valid, msg = remediator.validate_python_ast(patch_code)
    if not is_valid:
        print(json.dumps({"status": "FAILED", "ast_validation": msg}, indent=2))
        raise typer.Exit(code=1)
    with open(scraper_path, "w", encoding="utf-8") as f:
        f.write(patch_code)
    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "ast_validation": "PASSED",
                "replaced_file": f"bundles/{bundle_name}/scraper.py",
                "message": (
                    f"Replaced {scraper_path}. This is a full-file write, not a surgical diff. "
                    "Extractor selector drift belongs in extractors/<id>/extractor.py."
                ),
            },
            indent=2,
        )
    )


@app.command("test")
def test(
    bundle_name: str = typer.Argument(...),
    url: str | None = typer.Option(
        None,
        "--url",
        help="Live 1-page scrape URL. Without this, only import is checked.",
    ),
) -> None:
    """Import scraper.py; with --url run one live scrape (SUCCESS | ZERO_ROWS | FAILED)."""
    from apps.observability.ai_remediator import AIRemediatorEngine

    result = AIRemediatorEngine().run_verification_test(bundle_name, url=url)
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") not in {"SUCCESS", "IMPORT_OK"}:
        raise typer.Exit(code=1)
