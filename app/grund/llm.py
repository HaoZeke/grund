"""OpenAI-compatible chat client.

DGX Spark default is a local vLLM (or llama.cpp) server. LUMI can expose the
same shape. No key is required for a local server. If GRUND_LLM_BASE_URL is
unset the rest of Grund still answers: the deterministic planner and the
template sentence do not call a model.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import httpx

DEFAULT_MODEL = "Qwen/Qwen2.5-14B-Instruct"


@dataclass
class LLMSettings:
    base_url: str
    model: str
    api_key: str
    timeout: float

    @classmethod
    def from_env(cls) -> "LLMSettings":
        return cls(
            base_url=os.environ.get("GRUND_LLM_BASE_URL", "").rstrip("/"),
            model=os.environ.get("GRUND_LLM_MODEL", DEFAULT_MODEL),
            api_key=os.environ.get("GRUND_LLM_API_KEY", "local"),
            timeout=float(os.environ.get("GRUND_LLM_TIMEOUT", "90")),
        )

    def enabled(self) -> bool:
        return bool(self.base_url)


class ChatClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or LLMSettings.from_env()

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        response_format: dict | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.settings.enabled():
            raise RuntimeError("GRUND_LLM_BASE_URL is not set")
        url = self.settings.base_url + "/chat/completions"
        body: dict = {
            "model": self.settings.model,
            "temperature": temperature,
            "messages": messages,
        }
        if response_format is not None:
            body["response_format"] = response_format
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self.settings.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]


def parse_json_object(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model reply did not contain a JSON object")
    return json.loads(text[start : end + 1])
