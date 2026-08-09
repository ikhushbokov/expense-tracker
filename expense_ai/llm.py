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
import time

from openai import AsyncOpenAI, APIError, APITimeoutError

from expense_ai.config import settings

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a usable response after retries."""


class LLMClient:
    """Wraps an OpenAI-compatible client with JSON-mode + retry + fallback parsing.

    Optionally holds a second ("fallback") client for a different provider,
    tried only once the primary exhausts its own retries -- see
    settings.llm_base_url_fallback. No fallback configured (the default)
    means this behaves exactly as it did before the fallback existed.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.model = model or settings.llm_model
        self._client = self._build_client(base_url or settings.llm_base_url, api_key or settings.llm_api_key)

        self._fallback_client: AsyncOpenAI | None = None
        self._fallback_model = settings.llm_model_fallback or self.model
        if settings.llm_base_url_fallback:
            self._fallback_client = self._build_client(settings.llm_base_url_fallback, settings.llm_api_key_fallback)

    @staticmethod
    def _build_client(base_url: str, api_key: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",
            timeout=settings.llm_timeout_seconds,
            # The SDK retries transient errors (timeouts, connection resets) 2
            # more times by default -- on top of _attempt_all's own retry loop
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
        image_data_url: str | None = None,
        response_schema: dict | None = None,
    ) -> dict:
        """Ask the model for a JSON object and return it parsed as a dict.

        If ``image_data_url`` is given (a ``data:image/...;base64,...`` URI),
        it's attached alongside ``user_prompt`` as vision input -- see
        handlers/balance_sync.py's card-amount extraction for the only
        current caller.

        If ``response_schema`` is given (a JSON Schema dict, object type,
        ``additionalProperties: false``, every property listed in
        ``required``), the first attempt asks for strict schema-validated
        output (``response_format: json_schema``) instead of just
        well-formed JSON (``json_object``) -- stronger, but only worth
        building for a narrow, single-shape call; parser.py's general
        16-intent classifier doesn't use this, both because that would be
        real effort to get right across every intent shape and because
        every failure seen in production has been a network timeout, never
        malformed JSON the existing json_object + regex fallback couldn't
        already handle.

        Tries the primary provider (with its own internal retries -- see
        _attempt_all); if that's exhausted and a fallback provider is
        configured, tries the fallback the same way before giving up.
        """
        try:
            return await self._attempt_all(
                self._client,
                self.model,
                system_prompt,
                user_prompt,
                temperature,
                label="primary",
                image_data_url=image_data_url,
                response_schema=response_schema,
            )
        except LLMError as primary_error:
            if self._fallback_client is None:
                raise
            logger.warning("Primary LLM provider exhausted, trying fallback: %s", primary_error)
            try:
                return await self._attempt_all(
                    self._fallback_client,
                    self._fallback_model,
                    system_prompt,
                    user_prompt,
                    temperature,
                    label="fallback",
                    image_data_url=image_data_url,
                    response_schema=response_schema,
                )
            except LLMError as fallback_error:
                raise LLMError(
                    f"Both primary and fallback LLM providers failed. primary={primary_error}; fallback={fallback_error}"
                ) from fallback_error

    async def _attempt_all(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        *,
        label: str,
        image_data_url: str | None = None,
        response_schema: dict | None = None,
    ) -> dict:
        """Run the retry loop (schema/JSON-mode -> plain-text fallback
        parsing) against one client/model, raising LLMError once retries
        run out.

        Logs latency and outcome for every attempt (and the overall call)
        at INFO/WARNING/ERROR -- diagnosing a slow or degrading provider
        used to mean manually shelling into the container and hand-timing
        a call; this puts the same numbers in the regular logs as they
        happen.
        """
        user_content: str | list[dict] = user_prompt
        if image_data_url:
            user_content = [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]

        call_start = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(settings.llm_max_retries + 1):
            use_json_mode = attempt == 0
            use_reasoning_effort = attempt <= 1
            attempt_start = time.monotonic()
            try:
                kwargs: dict = {
                    "model": model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                }
                if use_json_mode and response_schema is not None:
                    kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {"name": "response", "strict": True, "schema": response_schema},
                    }
                elif use_json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                if use_reasoning_effort and settings.llm_reasoning_effort:
                    kwargs["reasoning_effort"] = settings.llm_reasoning_effort

                response = await client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content or ""
                result = _extract_json(content)
                logger.info(
                    "LLM call succeeded (provider=%s, model=%s, attempt=%s/%s, took=%.1fs, total=%.1fs)",
                    label,
                    model,
                    attempt + 1,
                    settings.llm_max_retries + 1,
                    time.monotonic() - attempt_start,
                    time.monotonic() - call_start,
                )
                return result
            except (APIError, APITimeoutError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (provider=%s, model=%s, attempt=%s/%s, json_mode=%s, took=%.1fs): %s",
                    label,
                    model,
                    attempt + 1,
                    settings.llm_max_retries + 1,
                    use_json_mode,
                    time.monotonic() - attempt_start,
                    exc,
                )

        logger.error(
            "LLM call failed after all retries (provider=%s, model=%s, total=%.1fs): %s",
            label,
            model,
            time.monotonic() - call_start,
            last_error,
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
