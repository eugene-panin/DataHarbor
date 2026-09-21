"""Tests for `harbor down`'s runtime selection (F13).

Before the fix, `down()` chose tilt whenever the `tilt` binary was merely
installed on PATH, regardless of which runtime was actually running —
forgetting `--compose` (which isn't remembered between `up`/`down` calls)
silently ran `tilt down` while the real Docker Compose stack stayed up.
"""
from __future__ import annotations

from unittest.mock import patch

from apps.cli.commands import platform as platform_module


def _run_down(*, compose_flag: bool, active_runtime: str, tilt_on_path: bool):
    """Invoke down() with runtime detection and subprocess execution mocked,
    returning the argv of the subprocess call it made."""
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)

        class _Result:
            returncode = 0

        return _Result()

    def _fake_which(binary):
        return "/usr/bin/tilt" if binary == "tilt" and tilt_on_path else None

    with (
        patch.object(platform_module, "check_active_runtime", return_value=active_runtime),
        patch.object(platform_module.shutil, "which", side_effect=_fake_which),
        patch.object(platform_module.subprocess, "run", side_effect=_fake_run),
    ):
        platform_module.down(compose=compose_flag)

    assert len(calls) == 1
    return calls[0]


def test_down_uses_compose_when_compose_is_actually_running_even_if_tilt_installed():
    """F13: tilt happens to be on PATH, but Compose is the active runtime and
    --compose wasn't passed — must still stop Compose, not run `tilt down`."""
    cmd = _run_down(compose_flag=False, active_runtime="DOCKER_COMPOSE", tilt_on_path=True)
    assert cmd == ["docker", "compose", "down"]


def test_down_uses_tilt_when_kubernetes_is_actually_running():
    cmd = _run_down(compose_flag=False, active_runtime="KUBERNETES", tilt_on_path=True)
    assert cmd == ["tilt", "down"]


def test_down_explicit_compose_flag_is_honored():
    cmd = _run_down(compose_flag=True, active_runtime="KUBERNETES", tilt_on_path=True)
    assert cmd == ["docker", "compose", "down"]


def test_down_nothing_running_falls_back_to_tilt_availability():
    cmd = _run_down(compose_flag=False, active_runtime="NONE", tilt_on_path=True)
    assert cmd == ["tilt", "down"]

    cmd = _run_down(compose_flag=False, active_runtime="NONE", tilt_on_path=False)
    assert cmd == ["docker", "compose", "down"]
