"""Filesystem paths for installed DataHarbor extractors."""
from __future__ import annotations

import os

from apps.cli.paths import PROJECT_ROOT

EXTRACTORS_DIR = os.path.join(PROJECT_ROOT, "extractors")
