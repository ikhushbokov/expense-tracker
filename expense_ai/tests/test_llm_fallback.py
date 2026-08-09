"""Tests for LLMClient's optional second-provider fallback.

Only the new orchestration in complete_json() is under test here (does it
try the fallback when configured, does it stay a no-op when it isn't) --
_attempt_all itself (the actual HTTP retry loop) is monkeypatched out
rather than simulating real openai SDK exceptions, since that logic is
unchanged from before this feature existed.
"""

from __future__ import annotations

import asyncio

import pytest

import expense_ai.llm as llm_module
from expense_ai.llm import LLMClient, LLMError


def _make_client(monkeypatch, *, fallback_url: str = "", fallback_model: str = "fallback-model") -> LLMClient:
    monkeypatch.setattr(llm_module.settings, "llm_base_url_fallback", fallback_url)
    monkeypatch.setattr(llm_module.settings, "llm_api_key_fallback", "fb-key")
    monkeypatch.setattr(llm_module.settings, "llm_model_fallback", fallback_model)
    return LLMClient(base_url="http://primary.invalid/v1", api_key="key", model="primary-model")


def test_no_fallback_configured_is_a_no_op(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="")
    assert client._fallback_client is None


def test_fallback_client_built_when_configured(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="http://fallback.invalid/v1")
    assert client._fallback_client is not None


def test_fallback_model_defaults_to_primary_when_unset(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="http://fallback.invalid/v1", fallback_model="")
    assert client._fallback_model == "primary-model"


def test_no_fallback_raises_primary_error_directly(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="")

    async def fail(*a, **kw):
        raise LLMError("primary down")

    monkeypatch.setattr(client, "_attempt_all", fail)

    with pytest.raises(LLMError, match="primary down"):
        asyncio.run(client.complete_json(system_prompt="s", user_prompt="u"))


def test_fallback_used_when_primary_fails(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="http://fallback.invalid/v1")

    calls = []

    async def fake_attempt_all(c, model, system_prompt, user_prompt, temperature, *, label, **kw):
        calls.append(label)
        if label == "primary":
            raise LLMError("primary down")
        return {"ok": True, "via": label}

    monkeypatch.setattr(client, "_attempt_all", fake_attempt_all)

    result = asyncio.run(client.complete_json(system_prompt="s", user_prompt="u"))
    assert result == {"ok": True, "via": "fallback"}
    assert calls == ["primary", "fallback"]


def test_fallback_not_tried_when_primary_succeeds(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="http://fallback.invalid/v1")

    calls = []

    async def fake_attempt_all(c, model, system_prompt, user_prompt, temperature, *, label, **kw):
        calls.append(label)
        return {"ok": True, "via": label}

    monkeypatch.setattr(client, "_attempt_all", fake_attempt_all)

    result = asyncio.run(client.complete_json(system_prompt="s", user_prompt="u"))
    assert result == {"ok": True, "via": "primary"}
    assert calls == ["primary"]


def test_both_providers_failing_raises_combined_error(monkeypatch):
    client = _make_client(monkeypatch, fallback_url="http://fallback.invalid/v1")

    async def fake_attempt_all(c, model, system_prompt, user_prompt, temperature, *, label, **kw):
        raise LLMError(f"{label} down")

    monkeypatch.setattr(client, "_attempt_all", fake_attempt_all)

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(client.complete_json(system_prompt="s", user_prompt="u"))
    assert "primary down" in str(exc_info.value)
    assert "fallback down" in str(exc_info.value)
