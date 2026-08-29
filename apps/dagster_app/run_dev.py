#!/usr/bin/env python3
"""Refresh a Dagster workspace profile then start ``dagster dev``.

Env:
  DAGSTER_WORKSPACE_NAME  profile from workspace_profiles.yaml (default: all)
  DAGSTER_WORKSPACE       explicit path to a workspace.yaml (overrides name)
  DAGSTER_DEV_HOST / DAGSTER_DEV_PORT  (default 0.0.0.0:3000)
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    from apps.dagster_app.workspace_builder import write_named_workspace

    host = os.getenv("DAGSTER_DEV_HOST", "0.0.0.0")
    port = os.getenv("DAGSTER_DEV_PORT", "3000")
    explicit = (os.getenv("DAGSTER_WORKSPACE") or "").strip()
    profile = (os.getenv("DAGSTER_WORKSPACE_NAME") or "all").strip() or "all"

    if explicit:
        workspace = os.path.abspath(explicit)
        if os.path.isfile(workspace):
            warnings: list[str] = []
        else:
            print(
                f"[workspace] missing {workspace}; generating profile '{profile}'",
                file=sys.stderr,
            )
            workspace, _doc, warnings = write_named_workspace(profile)
    else:
        workspace, _doc, warnings = write_named_workspace(profile)

    for w in warnings:
        print(f"[workspace] WARN: {w}", file=sys.stderr)
    print(f"[workspace] profile={profile} file={workspace}", file=sys.stderr)
    print(f"[workspace] UI http://localhost:{port}", file=sys.stderr)

    os.execvp(
        "dagster",
        [
            "dagster",
            "dev",
            "-h",
            host,
            "-p",
            port,
            "-w",
            workspace,
        ],
    )


if __name__ == "__main__":
    main()
