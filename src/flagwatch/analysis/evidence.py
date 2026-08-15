from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from flagwatch.domain import AiPolicy


@dataclass(frozen=True)
class EvidenceDocument:
    source_url: str
    text: str


class PolicyResult(BaseModel):
    policy: AiPolicy
    reason: str
    source_url: str | None = None
    evidence: str | None = None
    confidence: float = 0.0
    conflicting: bool = False
