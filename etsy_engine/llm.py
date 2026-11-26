"""Pluggable LLM layer. Free providers first; if none is configured or all fail,
callers fall back to the built-in rule-based copywriter, so the engine always runs.

  gemini    - Google AI Studio free tier            (GEMINI_API_KEY)
  groq      - Groq free tier                         (GROQ_API_KEY)
  anthropic - Claude, paid, optional                 (ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import Config
from .http import ApiError, HttpClient

log = logging.getLogger(__name__)

PROVIDER_KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def extract_json(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = HttpClient(qps=1.0, timeout=float(cfg.get("llm.timeout_seconds", 60)), max_retries=1)
        self.providers = [p for p in cfg.get("llm.providers", []) if cfg.secret(PROVIDER_KEYS.get(p, "-"))]
        self.last_provider: str | None = None
        self.disabled: set[str] = set()

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def generate_json(self, system: str, prompt: str, max_tokens: int = 3000) -> dict | None:
        for provider in self.providers:
            if provider in self.disabled:
                continue
            try:
                text = getattr(self, f"_{provider}")(system, prompt, max_tokens)
                data = extract_json(text)
                if isinstance(data, dict):
                    self.last_provider = provider
                    return data
            except ApiError as exc:
                log.warning("LLM provider %s failed: %s", provider, exc)
                if exc.status in (401, 403):
                    self.disabled.add(provider)
            except Exception as exc:  # bad JSON, SDK missing, etc.
                log.warning("LLM provider %s failed: %s", provider, exc)
        return None

    # ---- providers -------------------------------------------------------------
    def _gemini(self, system: str, prompt: str, max_tokens: int) -> str:
        models = [self.cfg.get("llm.gemini_model")] + list(self.cfg.get("llm.gemini_fallback_models", []) or [])
        for i, model in enumerate(models):
            try:
                return self._gemini_call(model, system, prompt, max_tokens)
            except ApiError as exc:
                # busy, quota, retired model or timeout -> try the next free model
                if exc.status in (0, 404, 429, 500, 503) and i < len(models) - 1:  # 0 = timeout/network
                    log.info("Gemini model %s unavailable (%s), trying %s", model, exc.status, models[i + 1])
                    continue
                raise
        return ""

    def _gemini_call(self, model: str, system: str, prompt: str, max_tokens: int) -> str:
        resp = self.http.request(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": self.cfg.secret("GEMINI_API_KEY")},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": self.cfg.get("llm.temperature", 0.7),
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            },
        ).json()
        parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def _groq(self, system: str, prompt: str, max_tokens: int) -> str:
        resp = self.http.request(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.secret('GROQ_API_KEY')}"},
            json={
                "model": self.cfg.get("llm.groq_model"),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": self.cfg.get("llm.temperature", 0.7),
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        ).json()
        return resp["choices"][0]["message"]["content"]

    def _anthropic(self, system: str, prompt: str, max_tokens: int) -> str:
        import anthropic  # optional dependency: pip install anthropic

        client = anthropic.Anthropic(api_key=self.cfg.secret("ANTHROPIC_API_KEY"))
        response = client.beta.messages.create(
            model=self.cfg.get("llm.anthropic_model"),
            max_tokens=max(max_tokens, 4000),
            system=system,
            messages=[{"role": "user", "content": prompt + "\n\nReturn only the JSON object."}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request")
        return "".join(block.text for block in response.content if block.type == "text")
