"""Discover and merge Dagster Definitions from installed bundles."""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from dagster import Definitions

from bundles.plugin_contract import (
    BundleContractError,
    iter_bundle_dirs,
    load_bundle_definitions_object,
)
from bundles.validator import BundleValidator

logger = logging.getLogger(__name__)

BUNDLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bundles")


def _skip_invalid_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is not None:
        return explicit
    return os.getenv("DATAHARBOR_SKIP_INVALID_BUNDLES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def discover_bundle_definitions(
    bundles_dir: Optional[str] = None,
    *,
    skip_invalid: Optional[bool] = None,
) -> List[Definitions]:
    """
    Load each valid bundle's ``Definitions``.

    By default invalid / unloadable bundles raise ``BundleContractError``.
    Set ``skip_invalid=True`` or env ``DATAHARBOR_SKIP_INVALID_BUNDLES=1`` for soft skip (dev).
    """
    root = bundles_dir or BUNDLES_DIR
    soft = _skip_invalid_enabled(skip_invalid)
    discovered: List[Definitions] = []

    for name, path in iter_bundle_dirs(root):
        is_valid, errors = BundleValidator(path).validate()
        if not is_valid:
            msg = f"Invalid bundle '{name}': " + "; ".join(errors)
            if soft:
                logger.warning("Skipping invalid bundle. %s", msg)
                continue
            raise BundleContractError(msg)

        try:
            defs = load_bundle_definitions_object(name, path)
        except BundleContractError as e:
            if soft:
                logger.warning("Skipping unloadable bundle '%s': %s", name, e)
                continue
            raise
        except Exception as e:
            msg = f"Failed to load Dagster definitions for bundle '{name}': {e}"
            if soft:
                logger.warning("%s", msg)
                continue
            raise BundleContractError(msg) from e

        discovered.append(defs)
        logger.info("Loaded Dagster Definitions from bundle '%s'", name)

    return discovered


def merge_bundle_definitions(
    *base_defs: Definitions,
    bundles_dir: Optional[str] = None,
    skip_invalid: Optional[bool] = None,
) -> Definitions:
    """Merge Core Definitions with all discovered bundle Definitions."""
    parts = [d for d in base_defs if d is not None]
    parts.extend(discover_bundle_definitions(bundles_dir, skip_invalid=skip_invalid))
    if not parts:
        return Definitions()
    if len(parts) == 1:
        return parts[0]
    return Definitions.merge(*parts)
