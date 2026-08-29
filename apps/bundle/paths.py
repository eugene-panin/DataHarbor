"""Filesystem paths for installed DataHarbor bundles."""
from __future__ import annotations

import os

from apps.cli.paths import PROJECT_ROOT

BUNDLES_DIR = os.path.join(PROJECT_ROOT, "bundles")
