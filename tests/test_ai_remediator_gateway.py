"""Tests for LLMProviderGateway's provider/key/model resolution (F18).

Before the fix, self.api_key was picked as the first non-empty key across
ALL providers' env vars regardless of AI_REPAIR_PROVIDER, and self.model
always defaulted to "gemini-1.5-flash" no matter which provider was
selected — so AI_REPAIR_PROVIDER=openai with a leftover GEMINI_API_KEY set
would silently send the Gemini key (and the Gemini model name) to OpenAI.
"""
from __future__ import annotations

from apps.observability.ai_remediator import LLMProviderGateway


def _clear_provider_env(monkeypatch):
    for var in (
        "AI_REPAIR_PROVIDER",
        "AI_REPAIR_API_KEY",
        "AI_REPAIR_MODEL",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_provider_only_uses_its_own_key_even_if_others_are_set(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-leftover-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-real-key")

    gateway = LLMProviderGateway()

    assert gateway.api_key == "openai-real-key"


def test_provider_default_model_matches_the_selected_provider(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-real-key")

    gateway = LLMProviderGateway()

    assert gateway.model == "gpt-4o-mini"


def test_deepseek_provider_gets_its_own_default_model_and_key(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-leftover-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-real-key")

    gateway = LLMProviderGateway()

    assert gateway.api_key == "deepseek-real-key"
    assert gateway.model == "deepseek-chat"


def test_ai_repair_api_key_overrides_provider_specific_key(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "openai")
    monkeypatch.setenv("AI_REPAIR_API_KEY", "explicit-override-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-real-key")

    gateway = LLMProviderGateway()

    assert gateway.api_key == "explicit-override-key"


def test_ai_repair_model_overrides_the_provider_default(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "openai")
    monkeypatch.setenv("AI_REPAIR_MODEL", "gpt-4-turbo")

    gateway = LLMProviderGateway()

    assert gateway.model == "gpt-4-turbo"


def test_no_key_configured_for_provider_is_empty_not_a_stray_key(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("AI_REPAIR_PROVIDER", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-leftover-key")

    gateway = LLMProviderGateway()

    assert gateway.api_key == ""
