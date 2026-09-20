"""Optional env keys are appended to core `.env`, not extra example files."""
from __future__ import annotations

from pathlib import Path

from apps.cli.env_files import ensure_compose_profile_env


def test_appends_profile_block_once(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("ADMIN_USER=admin\n", encoding="utf-8")
    note = ensure_compose_profile_env(tmp_path, "n8n")
    text = env.read_text(encoding="utf-8")
    assert "Created" not in note
    assert "Appended" in note
    assert text.count("N8N_INSTANCE_OWNER_EMAIL") == 1
    assert ensure_compose_profile_env(tmp_path, "n8n") == ""
    assert env.read_text(encoding="utf-8").count("N8N_INSTANCE_OWNER_EMAIL") == 1


def test_missing_env_file(tmp_path: Path):
    note = ensure_compose_profile_env(tmp_path, "n8n")
    assert "Missing .env" in note


def test_unknown_profile(tmp_path: Path):
    (tmp_path / ".env").write_text("x=1\n", encoding="utf-8")
    assert "No env block" in ensure_compose_profile_env(tmp_path, "nope")
