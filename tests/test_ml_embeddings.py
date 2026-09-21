"""Tests for apps.ml.embeddings (F22): no silent zero-padding, model caching.

sentence_transformers/torch aren't installed in the base dev environment
(optional `ml` extra) — stub the module so these run without it.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from apps.ml import embeddings as emb_module


class _FakeModel:
    def __init__(self, name, device):
        self.name = name
        self.device = device
        self.encode_calls = 0

    def encode(self, text):
        self.encode_calls += 1
        vec = MagicMock()
        vec.tolist.return_value = [0.1, 0.2, 0.3]  # a deliberately "wrong" length (not 512)
        return vec


@pytest.fixture(autouse=True)
def _clear_model_cache(monkeypatch):
    monkeypatch.setattr(emb_module, "_MODEL_CACHE", {})


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    created = {"count": 0, "instances": []}

    def _factory(name, device):
        created["count"] += 1
        instance = _FakeModel(name, device)
        created["instances"].append(instance)
        return instance

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _factory
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr("apps.ml.require_ml", lambda *a, **k: None)
    monkeypatch.setattr(emb_module, "get_best_torch_device", lambda: "cpu")
    return created


def test_embedding_is_not_zero_padded_to_a_fixed_size(fake_sentence_transformers):
    """F22: the model's real (short, 3-dim here) output must come back as-is,
    not silently stretched to a hardcoded 512 with meaningless zeros."""
    vector = emb_module.generate_multimodal_embedding("hello world")
    assert vector == [0.1, 0.2, 0.3]


def test_model_is_loaded_once_and_reused_across_calls(fake_sentence_transformers):
    """F22: SentenceTransformer(...) must not be reconstructed on every call —
    that reloads the model from disk each time."""
    emb_module.generate_multimodal_embedding("first call")
    emb_module.generate_multimodal_embedding("second call")

    assert fake_sentence_transformers["count"] == 1
    instance = fake_sentence_transformers["instances"][0]
    assert instance.encode_calls == 2
