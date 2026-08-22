"""Core Dagster Definitions only — bundles load as separate code locations."""
from dagster import (
    Definitions,
    load_asset_checks_from_modules,
    load_assets_from_modules,
)

from apps.dagster_app import assets as core_assets

defs = Definitions(
    assets=load_assets_from_modules([core_assets]),
    asset_checks=load_asset_checks_from_modules([core_assets]),
)
