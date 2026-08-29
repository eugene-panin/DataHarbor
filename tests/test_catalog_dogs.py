"""Tests for catalog dog pack scaffold."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from apps.bundle.scaffold import create_bundle

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"
NAME = "zz_dog_pack_demo"


def _cleanup() -> None:
    target = BUNDLES_ROOT / NAME
    if target.exists():
        shutil.rmtree(target)
    mod = f"bundles.{NAME}"
    for key in list(sys.modules):
        if key == mod or key.startswith(mod + "."):
            del sys.modules[key]


def test_dog_pack_enriches_and_quarantines():
    _cleanup()
    try:
        create_bundle(NAME, template="catalog", target_dir=str(BUNDLES_ROOT / NAME))
        from bundles.zz_dog_pack_demo.dogs import apply_dog_results, run_all_dogs
        from bundles.zz_dog_pack_demo.quarantine import process_rows_with_dogs

        row = {
            "sku": "SKU-1",
            "title": "Apple iPhone case black",
            "gtin": "5901234123457",
            "price": 19.99,
        }
        results = run_all_dogs(row)
        enriched, quarantine, _ = apply_dog_results(row, results)
        assert enriched.get("brand") == "Apple"
        assert enriched.get("color") == "Black"
        assert "category" in enriched or quarantine

        batch = process_rows_with_dogs([row, {"sku": "SKU-2", "title": "mystery gadget"}])
        assert batch["clean_count"] + batch["quarantine_count"] == 2
        assert batch["quarantine_count"] >= 1
    finally:
        _cleanup()


def test_dog_registry_has_five_dogs():
    _cleanup()
    try:
        create_bundle(NAME, template="catalog", target_dir=str(BUNDLES_ROOT / NAME))
        from bundles.zz_dog_pack_demo.dogs import DEFAULT_DOGS

        assert len(DEFAULT_DOGS) == 5
        assert {d.dog_id for d in DEFAULT_DOGS} == {"gtin", "brand", "color", "category", "price"}
    finally:
        _cleanup()
