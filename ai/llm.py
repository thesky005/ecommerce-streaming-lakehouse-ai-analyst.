"""Minimal client for any OpenAI-compatible chat-completions API (default: OpenRouter).

Provider and model come from the environment, so switching to Groq, Gemini's OpenAI
endpoint or a local Ollama server is a configuration change:

    OPENROUTER_API_KEY=...   (or LLM_API_KEY)
    LLM_BASE_URL=https://openrouter.ai/api/v1
    LLM_MODEL=nvidia/nemotron-3.5-super-vl:free
"""
import json
import os
import time

import requests


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self):
        self.base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")
        self.api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
        self.reasoning = os.getenv("LLM_REASONING", "true").lower() in ("1", "true", "yes")
        self.calls = 0

    @property
    def configured(self) -> bool:
        return bool(self.api_key) or "localhost" in self.base_url or "127.0.0.1" in self.base_url

    def chat(self, messages: list[dict], tools: list[dict] | None = None, timeout: int = 180) -> dict:
        """Send one chat-completions request and return the assistant message dict."""
        if not self.configured:
            raise LLMError("No API key configured. Set OPENROUTER_API_KEY in .env.")
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.reasoning:
            payload["reasoning"] = {"enabled": True}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Northstar Insights",
        }
        delay = 4.0
        for attempt in range(4):
            try:
                response = requests.post(f"{self.base_url}/chat/completions", headers=headers,
                                         data=json.dumps(payload), timeout=timeout)
            except requests.RequestException as error:
                if attempt == 3:
                    raise LLMError(f"Could not reach the LLM provider: {error}") from error
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(float(response.headers.get("retry-after", delay)))
                delay *= 2
                continue
            body = _json(response)
            if response.status_code >= 400 or "error" in body:
                message = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
                if response.status_code == 429:
                    message = f"{message or 'Rate limited'} (free models allow a limited number of requests per day)"
                raise LLMError(f"LLM provider error {response.status_code}: {message or response.text[:300]}")
            choices = body.get("choices") or []
            if not choices:
                raise LLMError(f"LLM provider returned no choices: {str(body)[:300]}")
            self.calls += 1
            return choices[0]["message"]
        raise LLMError("LLM request failed after retries.")


def _json(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"error": response.text[:500]}
