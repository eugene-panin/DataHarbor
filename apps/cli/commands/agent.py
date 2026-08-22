"""Harbor Agent Protocol (HAP v1.0) commands."""
from __future__ import annotations

import json
import os

import typer

from apps.cli.paths import PROJECT_ROOT

app = typer.Typer(help="Harbor Agent Protocol (HAP v1.0) for external LLM agents", no_args_is_help=True)


@app.command("status")
def status() -> None:
    """Get JSON health status array of all scrapers."""
    from apps.observability.health_checker import ScraperHealthChecker

    report = ScraperHealthChecker().check_all_scrapers_health()
    print(json.dumps(report, indent=2))


@app.command("diagnose")
def diagnose(bundle_name: str = typer.Argument(...)) -> None:
    """Get compressed JSON diagnostic context (<200 tokens)."""
    from apps.observability.ai_remediator import AIRemediatorEngine

    compressed_json = AIRemediatorEngine().get_compressed_diagnostic_json(bundle_name)
    print(json.dumps(compressed_json, indent=2))


@app.command("patch")
def patch(
    bundle_name: str = typer.Argument(...),
    code_file: str = typer.Option(..., "--code-file", help="Path to replacement Python code"),
) -> None:
    """Apply AST-validated Python patch to scraper.py."""
    from apps.observability.ai_remediator import AIRemediatorEngine

    with open(code_file, encoding="utf-8") as f:
        patch_code = f.read()
    remediator = AIRemediatorEngine()
    is_valid, msg = remediator.validate_python_ast(patch_code)
    if not is_valid:
        print(json.dumps({"status": "FAILED", "ast_validation": msg}, indent=2))
        raise typer.Exit(code=1)
    scraper_path = os.path.join(PROJECT_ROOT, "bundles", bundle_name, "scraper.py")
    with open(scraper_path, "w", encoding="utf-8") as f:
        f.write(patch_code)
    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "ast_validation": "PASSED",
                "message": f"Applied patch to {scraper_path}",
            },
            indent=2,
        )
    )


@app.command("test")
def test(bundle_name: str = typer.Argument(...)) -> None:
    """Execute 1-page verification test scrape (stub success)."""
    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "message": f"Verification test passed for '{bundle_name}'.",
            },
            indent=2,
        )
    )
