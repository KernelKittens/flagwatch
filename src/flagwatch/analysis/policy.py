from __future__ import annotations

import re
from collections.abc import Sequence

from flagwatch.analysis.evidence import EvidenceDocument, PolicyResult
from flagwatch.domain import AiPolicy

AI_TERMS = re.compile(r"\b(ai|llm|large language model|artificial intelligence)\b", re.IGNORECASE)
NATIVE_ALLOW = re.compile(
    r"\b(all forms of ai usage|all ai tools|unrestricted ai|ai[- ]native)\b.{0,32}"
    r"\b(allowed|permitted|welcome)\b",
    re.IGNORECASE,
)
ASSISTED_ALLOW = re.compile(
    r"\b(interactive ai assistance|ai assistance|ai-assisted code generation|use of ai)\b"
    r".{0,48}\b(allowed|permitted|encouraged|fine)\b",
    re.IGNORECASE,
)
SOLVING_PROHIBITION = re.compile(
    r"(?:\bno\s+(?:llms?|ai assistants?)\b.{0,72}\bsolv|"
    r"\b(?:all\s+)?ai usage\b.{0,40}\b(?:prohibited|forbidden|not allowed)\b|"
    r"\b(?:llms?|ai assistants?|ai tools?)\b.{0,72}\b(?:prohibited|forbidden|not allowed)\b|"
    r"\bchallenge (?:details|material)\b.{0,72}\bmust not\b.{0,40}\bai\b|"
    r"\bmust not\b.{0,72}\bchallenge (?:details|material)\b.{0,40}\bai\b)",
    re.IGNORECASE,
)
AUTOMATION_LIMIT = re.compile(
    r"\b(fully automated|autonomous)\b.{0,32}\b(solv|agent).{0,32}"
    r"\b(prohibited|forbidden|not allowed|banned)\b",
    re.IGNORECASE,
)


def _sentences(document: EvidenceDocument) -> list[tuple[str, str]]:
    values = re.split(r"(?<=[.!?])\s+|[\r\n]+", document.text)
    return [(document.source_url, value.strip()) for value in values if value.strip()]


def _excerpt(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized if len(normalized) <= 240 else f"{normalized[:237].rstrip()}..."


def classify_ai_policy(documents: Sequence[EvidenceDocument]) -> PolicyResult:
    sentences = [item for document in documents for item in _sentences(document)]
    relevant = [(source, text) for source, text in sentences if AI_TERMS.search(text)]
    native = [(source, text) for source, text in relevant if NATIVE_ALLOW.search(text)]
    assisted = [(source, text) for source, text in relevant if ASSISTED_ALLOW.search(text)]
    prohibited = [(source, text) for source, text in relevant if SOLVING_PROHIBITION.search(text)]
    automation_limited = [
        (source, text) for source, text in sentences if AUTOMATION_LIMIT.search(text)
    ]

    if prohibited and (native or assisted):
        source, text = prohibited[0]
        return PolicyResult(
            policy=AiPolicy.UNKNOWN,
            reason="Official AI-policy statements conflict",
            source_url=source,
            evidence=_excerpt(text),
            confidence=1.0,
            conflicting=True,
        )
    if prohibited:
        source, text = prohibited[0]
        return PolicyResult(
            policy=AiPolicy.HUMAN_ONLY,
            reason="AI-assisted challenge solving is prohibited",
            source_url=source,
            evidence=_excerpt(text),
            confidence=1.0,
        )
    if assisted:
        source, text = assisted[0]
        reason = (
            "Interactive AI is allowed, but automated solving is restricted"
            if automation_limited
            else "Interactive AI assistance is allowed"
        )
        return PolicyResult(
            policy=AiPolicy.AI_ASSISTED,
            reason=reason,
            source_url=source,
            evidence=_excerpt(text),
            confidence=0.95,
        )
    if native:
        source, text = native[0]
        return PolicyResult(
            policy=AiPolicy.AI_NATIVE,
            reason="The rules explicitly allow unrestricted AI use",
            source_url=source,
            evidence=_excerpt(text),
            confidence=0.95,
        )
    return PolicyResult(
        policy=AiPolicy.UNKNOWN,
        reason="No clear AI policy found",
        confidence=0.0,
    )
