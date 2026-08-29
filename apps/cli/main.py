"""DataHarbor harbor CLI — Typer entrypoint."""
from __future__ import annotations

import typer
from dotenv import load_dotenv

# CLI commands should use the same local configuration as Docker Compose.
# Explicit shell/production environment variables still take precedence.
load_dotenv(override=False)

from apps.cli.commands import (  # noqa: E402
    agent,
    backup,
    bundle,
    crawl,
    extractor,
    platform,
    skill,
    workspace,
)

app = typer.Typer(
    name="harbor",
    help="DataHarbor Master Core CLI — open-core data platform & self-healing scraper orchestrator",
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode="rich",
    epilog=(
        "Examples: [bold]harbor bundle new my_leads[/bold] · "
        "[bold]harbor extractor publish demo_site --dry-run[/bold] · "
        "[bold]harbor up --compose[/bold]"
    ),
)

app.command("doctor")(platform.doctor)
app.command("up")(platform.up)
app.command("down")(platform.down)
app.command("status")(platform.status)
app.command("health")(platform.health)
app.command("uninstall")(platform.uninstall)

app.add_typer(bundle.app, name="bundle")
app.add_typer(extractor.app, name="extractor")
app.add_typer(backup.app, name="backup")
app.add_typer(skill.app, name="skill")
app.add_typer(agent.app, name="agent-protocol")
app.add_typer(workspace.app, name="workspace")
app.add_typer(crawl.app, name="crawl")


def main() -> None:
    """Console-script compatible entry for older wrappers."""
    app()


if __name__ == "__main__":
    app()
