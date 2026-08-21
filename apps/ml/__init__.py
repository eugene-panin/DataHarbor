"""Optional ML helpers (Whisper, EasyOCR, embeddings, clustering).

Install extras:
    uv sync --extra ml
    # or: pip install 'dataharbor[ml]'

Core itself does not depend on torch / whisper / easyocr.
"""
from __future__ import annotations

from typing import Iterable, List

ML_EXTRA_HINT = (
    "Optional ML dependency missing. Install with: uv sync --extra ml "
    "(or pip install 'dataharbor[ml]')."
)

# Packages commonly needed by apps.ml modules (checked lazily).
ML_PACKAGE_NAMES = (
    "torch",
    "faster_whisper",
    "easyocr",
    "sentence_transformers",
    "hdbscan",
)


def ml_extra_installed(packages: Iterable[str] | None = None) -> bool:
    """Return True if the given packages (default: core ML set) are importable."""
    import importlib.util

    names = list(packages) if packages is not None else list(ML_PACKAGE_NAMES)
    return all(importlib.util.find_spec(name) is not None for name in names)


def require_ml(*packages: str) -> None:
    """Raise ImportError with install hint if required ML packages are missing."""
    import importlib.util

    missing: List[str] = [
        name for name in packages if importlib.util.find_spec(name) is None
    ]
    if missing:
        raise ImportError(f"{ML_EXTRA_HINT} Missing: {', '.join(missing)}")


__all__ = [
    "ML_EXTRA_HINT",
    "ML_PACKAGE_NAMES",
    "ml_extra_installed",
    "require_ml",
]
