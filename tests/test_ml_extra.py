"""Optional ML extra gate."""
from __future__ import annotations

import pytest

from apps.ml import ML_EXTRA_HINT, ml_extra_installed, require_ml


def test_require_ml_raises_with_hint():
    with pytest.raises(ImportError) as exc:
        require_ml("definitely_missing_pkg_xyz")
    assert "uv sync --extra ml" in str(exc.value) or ML_EXTRA_HINT.split("(")[0] in str(exc.value)


def test_ml_extra_installed_false_without_torch_stack():
    # Core env should not pull the full ML stack by default.
    assert ml_extra_installed(["definitely_missing_pkg_xyz"]) is False
