from __future__ import annotations

import pytest

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.policy import classify_ai_policy
from flagwatch.domain import AiPolicy


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("All forms of AI usage are allowed.", AiPolicy.AI_NATIVE),
        (
            "Interactive AI assistance is allowed. Fully automated solving agents are prohibited.",
            AiPolicy.AI_ASSISTED,
        ),
        (
            "No LLMs or AI assistants for solving challenges in any way. "
            "LLM-assisted code completion in your IDE is fine.",
            AiPolicy.HUMAN_ONLY,
        ),
        (
            "AI may explain general concepts, but challenge details must not be entered "
            "into AI tools.",
            AiPolicy.HUMAN_ONLY,
        ),
        ("All AI usage is prohibited during the competition.", AiPolicy.HUMAN_ONLY),
        ("We have a strict no-AI policy for this competition.", AiPolicy.HUMAN_ONLY),
        ("All challenge work must comply with the no-AI policy.", AiPolicy.HUMAN_ONLY),
        ("CubeCTF 2026: All A/D, no AI.", AiPolicy.HUMAN_ONLY),
        (
            "Do not use AI tools to automatically solve challenges on your behalf. "
            "Using AI to explain a concept you're stuck on is fine.",
            AiPolicy.AI_ASSISTED,
        ),
        (
            "Any tools are fine, including AI. They're helpers, not shortcuts.",
            AiPolicy.AI_NATIVE,
        ),
        (
            "Tools of any kind are permitted. This includes large language models.",
            AiPolicy.AI_NATIVE,
        ),
        (
            "We do not forbid you from using AI. Slopping is not disallowed.",
            AiPolicy.AI_NATIVE,
        ),
        ("No team size limit and separate AI/Human leaderboards.", AiPolicy.AI_NATIVE),
        ("Be respectful and do not share flags.", AiPolicy.UNKNOWN),
        ("This event has no published policy about AI.", AiPolicy.UNKNOWN),
        ("Challenges include an AI hacking category.", AiPolicy.UNKNOWN),
    ],
)
def test_classifies_ai_policy(text, expected):
    result = classify_ai_policy([EvidenceDocument("https://ctf.example/rules", text)])

    assert result.policy is expected
    if expected is not AiPolicy.UNKNOWN:
        assert result.source_url == "https://ctf.example/rules"
        assert result.evidence


def test_conflicting_policy_fails_closed():
    result = classify_ai_policy(
        [
            EvidenceDocument("https://ctf.example/rules", "All AI tools are allowed."),
            EvidenceDocument("https://ctf.example/terms", "AI assistants are prohibited."),
        ]
    )

    assert result.policy is AiPolicy.UNKNOWN
    assert result.conflicting is True
    assert "conflict" in result.reason.lower()
