import json

import httpx
import pytest
from pydantic import ValidationError

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.llm import LlmPolicyExtractor, parse_policy_response
from flagwatch.domain import AiPolicy


def test_normalizes_dirty_model_json_and_validates_schema():
    left_quote = "\u201c"
    right_quote = "\u201d"
    en_dash = "\u2013"
    raw = (
        "```json\n"
        f"{{{left_quote}policy{right_quote}: {left_quote}ai_assisted{right_quote}, "
        f"{left_quote}reason{right_quote}: {left_quote}Interactive help is allowed {en_dash} "
        f"agents are banned.{right_quote}, {left_quote}evidence{right_quote}: "
        f"{left_quote}Interactive AI assistance is allowed.{right_quote}, "
        f"{left_quote}confidence{right_quote}: 0.91}}\n```"
    )

    result = parse_policy_response(raw)

    assert result.policy is AiPolicy.AI_ASSISTED
    assert result.reason == "Interactive help is allowed - agents are banned."


def test_rejects_unrecognized_policy_from_model():
    with pytest.raises(ValidationError):
        parse_policy_response(
            '{"policy":"probably fine","reason":"guess","evidence":"none","confidence":0.2}'
        )


def test_optional_extractor_uses_strict_structured_response():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"policy":"ai_native","reason":"AI is allowed",'
                                '"evidence":"All AI tools are allowed.","confidence":0.98}'
                            )
                        }
                    }
                ]
            },
        )

    extractor = LlmPolicyExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        endpoint="https://models.example/v1/chat/completions",
        api_key="secret",
        model="policy-model",
    )

    result = extractor.try_extract([EvidenceDocument("https://ctf.example/rules", "AI rules")])

    assert result is not None
    assert result.policy is AiPolicy.AI_NATIVE
    assert requests[0].headers["api-key"] == "secret"
    request_payload = json.loads(requests[0].content)
    assert request_payload["response_format"]["type"] == "json_schema"
    assert "temperature" not in request_payload
