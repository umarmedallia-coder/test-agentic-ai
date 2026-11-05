"""Optional Ollama/OpenRouter JSON-schema adapters using the standard library."""
from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel

from app.llm.provider import LLMProviderError, LLMUsage

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        if provider not in {"ollama", "openrouter"}:
            raise ValueError("provider must be ollama or openrouter")
        if not base_url.startswith(("http://", "https://")) or not model.strip():
            raise ValueError("valid base_url and model are required")
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.provider == "openrouter":
            if not self.api_key:
                raise LLMProviderError("OpenRouter API key is not configured")
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not expose request headers or credentials in the error.
            raise LLMProviderError(f"{self.provider} returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"{self.provider} request failed: {type(exc).__name__}") from exc

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_model: type[T],
    ) -> tuple[T, LLMUsage]:
        if not system_prompt.strip():
            raise ValueError("system_prompt cannot be empty")
        schema = output_model.model_json_schema()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ]
        if self.provider == "ollama":
            body = {
                "model": self.model, "stream": False, "format": schema,
                "messages": messages, "options": {"temperature": 0},
            }
            path = "/api/chat"
        else:
            body = {
                "model": self.model, "temperature": 0, "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_model.__name__.lower(),
                        "strict": True,
                        "schema": schema,
                    },
                },
            }
            path = "/chat/completions"
        response = await asyncio.wait_for(
            asyncio.to_thread(self._post_json, path, body),
            timeout=self.timeout_seconds + 1,
        )
        try:
            estimated_cost = None
            if self.provider == "ollama":
                raw = response["message"]["content"]
                prompt_tokens = int(response.get("prompt_eval_count", 0))
                completion_tokens = int(response.get("eval_count", 0))
            else:
                raw = response["choices"][0]["message"]["content"]
                usage_data = response.get("usage", {})
                prompt_tokens = int(usage_data.get("prompt_tokens", 0))
                completion_tokens = int(usage_data.get("completion_tokens", 0))
                if usage_data.get("cost") is not None:
                    estimated_cost = float(usage_data["cost"])
            parsed = output_model.model_validate_json(raw)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMProviderError("provider response did not match the requested schema") from exc
        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=estimated_cost,
        )
        return parsed, usage
