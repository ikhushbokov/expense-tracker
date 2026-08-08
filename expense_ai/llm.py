"""Thin async wrapper around any OpenAI-compatible chat-completions endpoint.

Because OpenAI, OpenRouter, Ollama, vLLM, LM Studio and most local model
servers all speak the same ``/v1/chat/completions`` protocol, switching
providers is just a matter of changing ``LLM_BASE_URL`` / ``LLM_API_KEY`` /
``LLM_MODEL`` in ``.env`` -- no code changes required.
"""

from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI, APIError, APITimeoutError

from expense_ai.config import settings

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a usable response after retries."""


class LLMClient:
    """Wraps an OpenAI-compatible client with JSON-mode + retry + fallback parsing."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or settings.llm_model
        self._client = AsyncOpenAI(
            base_url=base_url or settings.llm_base_url,
            api_key=api_key or settings.llm_api_key or "not-needed",
            timeout=settings.llm_timeout_seconds,
            # The SDK retries transient errors (timeouts, connection resets) 2
            # more times by default -- on top of complete_json's own retry loop
            # below, which exists for a different reason (falling back off
            # JSON mode / reasoning_effort for endpoints that reject them). The
            # two compound: a single hung request could silently cost up to
            # (llm_max_retries+1) * 3 * llm_timeout_seconds before surfacing as
            # one failure. Since we already have an outer retry loop, let each
            # of *our* attempts fail fast instead of retrying underneath it too.
            max_retries=0,
            # Some reverse-proxy / relay endpoints run bot-detection (Cloudflare
            # WAF etc.) that blocks the SDK's default "AsyncOpenAI/Python..." +
            # x-stainless-* fingerprint. A plain client User-Agent avoids that
            # without affecting behavior against official providers.
            default_headers={"User-Agent": "python-httpx"},
        )

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
    ) -> dict:
        """Ask the model for a JSON object and return it parsed as a dict.

        Tries native JSON response-format mode first (supported by OpenAI,
        OpenRouter, and most modern local servers); if the endpoint rejects
        that parameter, retries without it and extracts the first
        top-level ``{...}`` block from the raw text.
        """
        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            use_json_mode = attempt == 0
            use_reasoning_effort = attempt <= 1
            try:
                kwargs: dict = {
                    "model": self.model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }
                if use_json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                if use_reasoning_effort and settings.llm_reasoning_effort:
                    kwargs["reasoning_effort"] = settings.llm_reasoning_effort

                response = await self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                return _extract_json(content)
            except (APIError, APITimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (attempt %s/%s, json_mode=%s): %s",
                    attempt + 1,
                    settings.llm_max_retries + 1,
                    use_json_mode,
                    exc,
                )

        raise LLMError(f"LLM failed to produce valid JSON after retries: {last_error}") from last_error


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text!r}")
    return json.loads(match.group(0))


llm_client = LLMClient()
