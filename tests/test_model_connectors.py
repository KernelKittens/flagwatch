from __future__ import annotations

import json

import httpx
import pytest

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.llm import LlmPolicyExtractor
from flagwatch.analysis.providers import (
    AnthropicMessagesConnector,
    OpenAICompatibleConnector,
    StructuredOutputMode,
    build_model_connector,
)

MODEL_RESULT = (
    '{"policy":"unknown","reason":"No published AI policy",'
    '"evidence":"","confidence":0.0,"claims":[]}'
)


def test_openai_compatible_connector_supports_bearer_and_json_schema() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": MODEL_RESULT}}]},
        )

    connector = OpenAICompatibleConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint="https://models.example/v1",
        api_key="openai-secret",
        model="gpt-compatible",
    )

    result = connector.complete("system", "user", {"type": "object"})

    assert result == MODEL_RESULT
    assert requests[0].url == "https://models.example/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer openai-secret"
    body = json.loads(requests[0].content)
    assert body["response_format"]["type"] == "json_schema"
    assert "temperature" not in body


def test_openai_compatible_connector_can_use_json_object_for_deepseek() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": MODEL_RESULT}}]})

    connector = OpenAICompatibleConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint="https://api.deepseek.com",
        api_key="deepseek-secret",
        model="deepseek-chat",
        structured_output=StructuredOutputMode.JSON_OBJECT,
    )

    assert connector.complete("system", "user", {"type": "object"}) == MODEL_RESULT
    body = json.loads(requests[0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_local_openai_connector_omits_authorization_without_a_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": MODEL_RESULT}}]})

    connector = build_model_connector(
        provider="local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint="http://model.internal:11434/v1",
        api_key=None,
        model="qwen3",
    )

    assert connector.complete("system", "user", {"type": "object"}) == MODEL_RESULT
    assert "authorization" not in requests[0].headers


def test_anthropic_connector_uses_messages_api_and_extracts_text() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": MODEL_RESULT}]},
        )

    connector = AnthropicMessagesConnector(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint="https://api.anthropic.com",
        api_key="anthropic-secret",
        model="claude-sonnet",
    )

    assert connector.complete("system", "user", {"type": "object"}) == MODEL_RESULT
    assert requests[0].url == "https://api.anthropic.com/v1/messages"
    assert requests[0].headers["x-api-key"] == "anthropic-secret"
    assert requests[0].headers["anthropic-version"] == "2023-06-01"
    body = json.loads(requests[0].content)
    assert body["system"].startswith("system")
    assert "Output JSON Schema" in body["system"]


@pytest.mark.parametrize("provider", ["openai", "deepseek", "litellm", "local", "azure_openai"])
def test_factory_routes_openai_compatible_providers(provider: str) -> None:
    connector = build_model_connector(
        provider=provider,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
        endpoint="https://models.example/v1",
        api_key="key",
        model="model",
    )

    assert isinstance(connector, OpenAICompatibleConnector)


def test_factory_routes_anthropic_and_rejects_unknown_provider() -> None:
    connector = build_model_connector(
        provider="anthropic",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(500))),
        endpoint="https://api.anthropic.com",
        api_key="key",
        model="claude-sonnet",
    )

    assert isinstance(connector, AnthropicMessagesConnector)
    with pytest.raises(ValueError, match="Unsupported model provider"):
        build_model_connector(
            provider="pydanticai",
            client=httpx.Client(),
            endpoint="https://models.example",
            api_key=None,
            model="model",
        )


def test_policy_extractor_accepts_a_replaceable_connector() -> None:
    class StaticConnector:
        model = "static-test-model"

        def complete(self, system_prompt: str, user_prompt: str, schema: dict[str, object]) -> str:
            assert "hostile" in system_prompt
            assert "SOURCE: https://ctf.example/rules" in user_prompt
            assert schema["type"] == "object"
            return MODEL_RESULT

    extractor = LlmPolicyExtractor(connector=StaticConnector())

    result = extractor.try_extract(
        [EvidenceDocument("https://ctf.example/rules", "No AI policy is published.")]
    )

    assert extractor.model == "static-test-model"
    assert result is not None
    assert result.reason == "No published AI policy"
