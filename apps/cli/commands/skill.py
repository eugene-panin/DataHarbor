"""AI agent skill management commands."""
from __future__ import annotations

import typer

app = typer.Typer(help="AI Agent Skill Management Engine", no_args_is_help=True)


@app.command("install")
def install_skills() -> None:
    """Install bundled skills and inject runtime environment context."""
    from apps.skills.skill_manager import SkillManagerEngine

    print("\n🤖 Installing DataHarbor AI Agent Skills & Resolving Runtime Environment...")
    print("=" * 70)
    manager = SkillManagerEngine()
    res = manager.install_bundled_skills()
    env = res["environment"]
    print(f"  🌐 Active Environment Detected: {env['mode']} ({env['description']})")
    print("  Installed Skills:")
    for sk in res["installed_skills"]:
        print(f"    - {sk}")
    print("=" * 70)
    print(
        "✨ Skills successfully installed and registered for Codex, Antigravity, "
        "Claude Code, and Gemini CLI!\n"
    )


@app.command("list")
@app.command("status")
def list_skills() -> None:
    """List installed AI agent skills and detected target runtime."""
    from apps.skills.skill_manager import SkillManagerEngine

    print("\n🤖 INSTALLED DATAHARBOR AI AGENT SKILLS:")
    print("=" * 70)
    skills = SkillManagerEngine().list_installed_skills()
    if not skills:
        print("No skills currently installed.")
        print("Run 'harbor skill install' to install bundled skills.\n")
        return
    for s in skills:
        print(f"• {s['name']:<30} [Target: {s['target_environment']}]")
        print(f"  Path: {s['path']}")
    print("=" * 70 + "\n")
