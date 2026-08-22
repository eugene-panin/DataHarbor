"""Publish DataHarbor bundles/extractors to a git remote (gh optional)."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Literal

from apps.cli.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

PluginKind = Literal["bundle", "extractor"]

_IGNORE_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    ".env",
    ".env.local",
    ".DS_Store",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
}


@dataclass
class PublishReadiness:
    git_ok: bool
    git_path: str | None
    git_user_name: str | None
    git_user_email: str | None
    gh_ok: bool
    gh_path: str | None
    gh_authed: bool
    ssh_key_found: bool
    hard_failures: list[str]
    warnings: list[str]

    @property
    def can_commit(self) -> bool:
        return self.git_ok and bool(self.git_user_name) and bool(self.git_user_email)

    @property
    def can_auto_create_github(self) -> bool:
        return self.gh_ok and self.gh_authed


def _run(
    cmd: list[str],
    *,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _git_config(key: str) -> str | None:
    if not shutil.which("git"):
        return None
    try:
        out = _run(["git", "config", "--get", key], check=False)
        value = (out.stdout or "").strip()
        return value or None
    except Exception:
        return None


def check_publish_readiness() -> PublishReadiness:
    """NFR checks for publish/install git workflow."""
    hard: list[str] = []
    warnings: list[str] = []

    git_path = shutil.which("git")
    git_ok = bool(git_path)
    if not git_ok:
        hard.append("git is not on PATH (required for install/publish)")

    name = _git_config("user.name")
    email = _git_config("user.email")
    if git_ok and not name:
        warnings.append("git user.name is not set (required to commit on publish)")
    if git_ok and not email:
        warnings.append("git user.email is not set (required to commit on publish)")

    gh_path = shutil.which("gh")
    gh_ok = bool(gh_path)
    gh_authed = False
    if not gh_ok:
        warnings.append("gh not found (optional; needed only for auto-creating GitHub repos)")
    else:
        auth = _run(["gh", "auth", "status"], check=False)
        gh_authed = auth.returncode == 0
        if not gh_authed:
            warnings.append("gh is installed but not authenticated (run: gh auth login)")

    ssh_dir = os.path.expanduser("~/.ssh")
    ssh_key_found = False
    if os.path.isdir(ssh_dir):
        for entry in os.listdir(ssh_dir):
            if entry.startswith("id_") and entry.endswith(".pub"):
                ssh_key_found = True
                break
    if not ssh_key_found:
        warnings.append(
            "No ~/.ssh/id_*.pub found (SSH push may need a key or HTTPS credentials)"
        )

    return PublishReadiness(
        git_ok=git_ok,
        git_path=git_path,
        git_user_name=name,
        git_user_email=email,
        gh_ok=gh_ok,
        gh_path=gh_path,
        gh_authed=gh_authed,
        ssh_key_found=ssh_key_found,
        hard_failures=hard,
        warnings=warnings,
    )


def _plugin_root(kind: PluginKind, name: str) -> str:
    base = "bundles" if kind == "bundle" else "extractors"
    path = os.path.join(PROJECT_ROOT, base, name)
    if not os.path.isdir(path):
        raise ValueError(f"{kind.capitalize()} '{name}' not found at {path}")
    manifest = os.path.join(path, "manifest.json")
    if not os.path.exists(manifest):
        raise ValueError(f"{kind.capitalize()} '{name}' is missing manifest.json")
    return path


def _validate_plugin(kind: PluginKind, path: str) -> None:
    if kind == "bundle":
        from bundles.validator import BundleValidator

        ok, errors = BundleValidator(path).validate()
    else:
        from extractors.validator import ExtractorValidator

        ok, errors = ExtractorValidator(path).validate()
    if not ok:
        raise ValueError(
            f"{kind.capitalize()} validation failed:\n  - " + "\n  - ".join(errors)
        )


def _copy_plugin_snapshot(src: str, dest: str) -> None:
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    def _ignore(directory: str, names: list[str]) -> list[str]:
        ignored = []
        for name in names:
            if name in _IGNORE_NAMES or name.endswith(".pyc"):
                ignored.append(name)
        return ignored

    # copytree into dest contents
    for entry in os.listdir(src):
        if entry in _IGNORE_NAMES or entry.endswith(".pyc"):
            continue
        s = os.path.join(src, entry)
        d = os.path.join(dest, entry)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=_ignore)
        else:
            shutil.copy2(s, d)


def _default_repo_name(kind: PluginKind, name: str) -> str:
    prefix = "dh-bundle" if kind == "bundle" else "dh-extractor"
    return f"{prefix}-{name.replace('_', '-')}"


def _ensure_git_repo(staging: str, message: str) -> None:
    if not os.path.isdir(os.path.join(staging, ".git")):
        _run(["git", "init"], cwd=staging)
        _run(["git", "branch", "-M", "main"], cwd=staging, check=False)
    _run(["git", "add", "-A"], cwd=staging)
    status = _run(["git", "status", "--porcelain"], cwd=staging, check=False)
    if (status.stdout or "").strip():
        _run(["git", "commit", "-m", message], cwd=staging)


def _remote_exists(staging: str) -> bool:
    out = _run(["git", "remote"], cwd=staging, check=False)
    remotes = (out.stdout or "").split()
    return "origin" in remotes


def _set_origin(staging: str, remote: str) -> None:
    if _remote_exists(staging):
        _run(["git", "remote", "set-url", "origin", remote], cwd=staging)
    else:
        _run(["git", "remote", "add", "origin", remote], cwd=staging)


def _github_https_to_ssh(url: str) -> str:
    # https://github.com/org/repo.git -> git@github.com:org/repo.git
    if url.startswith("https://github.com/"):
        path = url.removeprefix("https://github.com/").removesuffix(".git")
        return f"git@github.com:{path}.git"
    return url


def _resolve_origin_url(staging: str) -> str:
    out = _run(["git", "remote", "get-url", "origin"], cwd=staging, check=False)
    return (out.stdout or "").strip()


def publish_plugin(
    kind: PluginKind,
    name: str,
    *,
    remote: str | None = None,
    workdir: str | None = None,
    repo_name: str | None = None,
    visibility: str = "private",
    dry_run: bool = False,
    allow_local_extractors: bool = False,
) -> dict[str, Any]:
    """Validate, stage, and publish a bundle/extractor to a git remote."""
    visibility_norm = (visibility or "private").strip().lower()
    if visibility_norm not in {"private", "public"}:
        raise ValueError("visibility must be 'private' or 'public'")

    readiness = check_publish_readiness()
    if readiness.hard_failures:
        raise ValueError("; ".join(readiness.hard_failures))
    if not readiness.can_commit and not dry_run:
        raise ValueError(
            "git user.name / user.email must be configured before publish. "
            "Run: git config --global user.name '...' && "
            "git config --global user.email '...'"
        )

    source = _plugin_root(kind, name)
    _validate_plugin(kind, source)

    unpublished: list[dict[str, Any]] = []
    if kind == "bundle":
        from extractors.requirements import find_unpublished_local_extractors

        unpublished = find_unpublished_local_extractors(source)
        if unpublished and not allow_local_extractors and not dry_run:
            lines = [
                f"Bundle '{name}' depends on local extractors that are not published "
                f"as git remotes yet:"
            ]
            for item in unpublished:
                lines.append(f"  • {item['name']} — {item['reason']}")
                lines.append(f"      → {item['suggest']}")
            lines.append(
                "Publish those extractors first (platform will not auto-create them), "
                "then update requirements.extractors to git URLs — or pass "
                "--allow-local-extractors to continue anyway."
            )
            raise ValueError("\n".join(lines))

    repo = repo_name or _default_repo_name(kind, name)
    commit_message = f"Publish {kind} {name}"

    use_temp = workdir is None
    if workdir:
        staging = os.path.abspath(workdir)
        os.makedirs(os.path.dirname(staging) or staging, exist_ok=True)
    else:
        staging = tempfile.mkdtemp(prefix=f"dh-publish-{kind}-{name}-")

    try:
        _copy_plugin_snapshot(source, staging)

        if dry_run:
            plan = {
                "status": "dry_run",
                "kind": kind,
                "name": name,
                "source": source,
                "staging": staging,
                "repo_name": repo,
                "visibility": visibility_norm,
                "remote": remote,
                "unpublished_extractors": unpublished,
                "mode": (
                    "remote"
                    if remote
                    else ("gh" if readiness.can_auto_create_github else "blocked")
                ),
                "install_hint": None,
            }
            if remote:
                plan["install_hint"] = f"harbor {kind} install {remote}"
            elif readiness.can_auto_create_github:
                plan["install_hint"] = (
                    f"harbor {kind} install git@github.com:<you>/{repo}.git"
                )
            return plan

        _ensure_git_repo(staging, commit_message)

        if remote:
            _set_origin(staging, remote)
            _run(["git", "push", "-u", "origin", "HEAD"], cwd=staging)
            origin = remote
            mode = "remote"
        elif readiness.can_auto_create_github:
            if _remote_exists(staging):
                _run(["git", "push", "-u", "origin", "HEAD"], cwd=staging)
                origin = _resolve_origin_url(staging)
                mode = "gh-existing-remote"
            else:
                cmd = [
                    "gh",
                    "repo",
                    "create",
                    repo,
                    f"--{visibility_norm}",
                    "--source=.",
                    "--remote=origin",
                    "--push",
                ]
                result = _run(cmd, cwd=staging, check=False)
                if result.returncode != 0:
                    details = (result.stderr or result.stdout or "").strip()
                    raise ValueError(f"gh repo create failed: {details[-2000:]}")
                origin = _resolve_origin_url(staging) or f"git@github.com:{repo}.git"
                mode = "gh"
        else:
            raise ValueError(
                "No --remote provided and GitHub auto-create is unavailable. "
                "Provide --remote git@host:org/repo.git or run `gh auth login`."
            )

        install_url = _github_https_to_ssh(origin) if origin else origin
        return {
            "status": "success",
            "kind": kind,
            "name": name,
            "source": source,
            "staging": staging if not use_temp else None,
            "repo_name": repo,
            "visibility": visibility_norm,
            "remote": origin,
            "install_url": install_url,
            "mode": mode,
            "unpublished_extractors": unpublished,
            "message": f"{kind.capitalize()} '{name}' published to {origin}",
            "install_hint": f"harbor {kind} install {install_url}",
        }
    finally:
        if use_temp and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
