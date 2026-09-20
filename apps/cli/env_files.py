"""Core `.env` is the only env file. Optional platform stack keys (compose profiles)
are appended here when enabled. Bundle-declared keys (manifest `requirements.env`)
are only ever printed as an install hint — see `apps/bundle/env_requirements.py` —
never auto-written, since their values and defaults are the bundle author's call.
"""
from __future__ import annotations

from pathlib import Path

# Sentinel key → block written into `.env` the first time the profile is enabled.
COMPOSE_PROFILE_ENV_BLOCKS: dict[str, tuple[str, str]] = {
    "n8n": (
        "N8N_INSTANCE_OWNER_EMAIL",
        "\n".join(
            [
                "",
                "# --- n8n (added by harbor up --with-n8n) ---",
                "N8N_INSTANCE_OWNER_EMAIL=admin@dataharbor.local",
                "N8N_INSTANCE_OWNER_FIRST_NAME=Admin",
                "N8N_INSTANCE_OWNER_LAST_NAME=User",
                "# bcrypt for admin123; regenerate after changing the password:",
                '# python -c "import bcrypt; print(bcrypt.hashpw(b\'YOUR_PASSWORD\', bcrypt.gensalt()).decode())"',
                "N8N_INSTANCE_OWNER_PASSWORD_HASH='$2a$10$VcCXQbXtMRCFQmXYLyb2yeeCHmnulnCgg4p79F0xvLoU/ZJyKPM7i'",
                "",
            ]
        ),
    ),
}

def _append_env_block(project_root: Path, sentinel: str, block: str, *, missing: str, appended: str) -> str:
    env_path = Path(project_root) / ".env"
    if not env_path.is_file():
        return missing
    text = env_path.read_text(encoding="utf-8")
    if sentinel in text:
        return ""
    env_path.write_text(text.rstrip() + "\n" + block, encoding="utf-8")
    return appended


def ensure_compose_profile_env(project_root: Path, profile: str) -> str:
    """Append profile keys to `.env` once, when that optional component is enabled."""
    spec = COMPOSE_PROFILE_ENV_BLOCKS.get(profile)
    if not spec:
        return f"No env block registered for compose profile {profile!r}."
    sentinel, block = spec
    return _append_env_block(
        project_root,
        sentinel,
        block,
        missing="Missing .env — copy .env.example first, then re-run with the optional profile.",
        appended=f"Appended {profile} settings to .env. Edit that block, then restart the service if needed.",
    )

