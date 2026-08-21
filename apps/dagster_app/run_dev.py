#!/usr/bin/env python3
"""Refresh workspace.yaml then start Dagster dev with multi code locations."""
from __future__ import annotations

import os
import sys


def main() -> None:
    from apps.dagster_app.workspace_builder import DEFAULT_WORKSPACE_PATH, write_workspace_yaml

    host = os.getenv("DAGSTER_DEV_HOST", "0.0.0.0")
    port = os.getenv("DAGSTER_DEV_PORT", "3000")
    workspace, _doc, warnings = write_workspace_yaml(DEFAULT_WORKSPACE_PATH)
    for w in warnings:
        print(f"[workspace] WARN: {w}", file=sys.stderr)
    print(f"[workspace] Using {workspace}", file=sys.stderr)

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
