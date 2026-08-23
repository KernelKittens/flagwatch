from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol

import httpx


class StructuredOutputMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_ONLY = "prompt_only"


class ModelConnector(Protocol):
    model: str

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> str | None: ...


def _openai_completion_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


def _anthropic_messages_endpoint(endpoint: str) -> str:
    normalized = endpoint.rstrip("/")
    if normalized.endswith("/messages"):
        return normalized
    if normalized.endswith("/v1"):
        return normalized + "/messages"
    return normalized + "/v1/messages"


class OpenAICompatibleConnector:
    def __init__(
        self,
        client: httpx.Client,
        endpoint: str,
        api_key: str | None,
        model: str,
        *,
        auth_header: str = "Authorization",
        structured_output: StructuredOutputMode = StructuredOutputMode.JSON_SCHEMA,
    ) -> None:
        self.client = client
        self.endpoint = _openai_completion_endpoint(endpoint)
        self.api_key = api_key
        self.model = model
        self.auth_header = auth_header
        self.structured_output = structured_output

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> str | None:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header] = (
                f"Bearer {self.api_key}"
                if self.auth_header.casefold() == "authorization"
                else self.api_key
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 2400,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.structured_output is StructuredOutputMode.JSON_SCHEMA:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "ctf_event_intelligence",
                    "strict": True,
                    "schema": schema,
                },
            }
        elif self.structured_output is StructuredOutputMode.JSON_OBJECT:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self.client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return content if isinstance(content, str) else None
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None


class AnthropicMessagesConnector:
    def __init__(
        self,
        client: httpx.Client,
        endpoint: str,
        api_key: str | None,
        model: str,
        *,
        anthropic_version: str = "2023-06-01",
    ) -> None:
        self.client = client
        self.endpoint = _anthropic_messages_endpoint(endpoint)
        self.api_key = api_key
        self.model = model
        self.anthropic_version = anthropic_version

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
    ) -> str | None:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        schema_text = json.dumps(schema, separators=(",", ":"), sort_keys=True)
        payload = {
            "model": self.model,
            "max_tokens": 2400,
            "system": f"{system_prompt}\n\nOutput JSON Schema:\n{schema_text}",
            "messages": [{"role": "user", "content": user_prompt}],
        }
        try:
            response = self.client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            blocks = body["content"]
            if not isinstance(blocks, list):
                return None
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        return text
            return None
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


def build_model_connector(
    *,
    provider: str,
    client: httpx.Client,
    endpoint: str,
    api_key: str | None,
    model: str,
) -> ModelConnector:
    normalized = provider.strip().casefold().replace("-", "_")
    if normalized == "anthropic":
        return AnthropicMessagesConnector(client, endpoint, api_key, model)
    if normalized in {"openai", "litellm"}:
        return OpenAICompatibleConnector(client, endpoint, api_key, model)
    if normalized == "azure_openai":
        return OpenAICompatibleConnector(
            client,
            endpoint,
            api_key,
            model,
            auth_header="api-key",
        )
    if normalized in {"deepseek", "local"}:
        return OpenAICompatibleConnector(
            client,
            endpoint,
            api_key,
            model,
            structured_output=StructuredOutputMode.JSON_OBJECT,
        )
    raise ValueError(f"Unsupported model provider: {provider}")
