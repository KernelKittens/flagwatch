from __future__ import annotations

import re
from collections.abc import Sequence

from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.policy import classify_ai_policy
from flagwatch.domain import EventFacts, ScheduleMode

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _team_max(text: str) -> int | None:
    match = re.search(
        r"teams?(?:\s+may|\s+can)?(?:\s+include|\s+consist\s+of|\s+of)?\s+up\s+to\s+"
        r"(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        range_match = re.search(r"teams?\s+of\s+\d+\s*[-to]+\s*(?P<count>\d+)", text, re.I)
        return int(range_match.group("count")) if range_match else None
    raw = match.group("count").lower()
    return int(raw) if raw.isdigit() else NUMBER_WORDS[raw]


def _divisions(text: str) -> list[str]:
    match = re.search(r"divisions?\s*:\s*(?P<values>[^.\r\n]+)", text, re.IGNORECASE)
    if not match:
        return []
    normalized = re.sub(r"\s+and\s+", ", ", match.group("values"), flags=re.IGNORECASE)
    return [value.strip(" ,") for value in normalized.split(",") if value.strip(" ,")]


def _schedule_mode(text: str, current: ScheduleMode) -> ScheduleMode:
    if re.search(r"\bstaggered\s+start", text, re.IGNORECASE):
        return ScheduleMode.STAGGERED
    if re.search(r"\b(rolling\s+start|start\s+anytime|choose your start)\b", text, re.I):
        return ScheduleMode.ROLLING
    if re.search(r"\b(qualifier|qualification)\b", text, re.I) and re.search(
        r"\bfinal(?:s| stage)?\b", text, re.I
    ):
        return ScheduleMode.MULTI_STAGE
    return current


def extract_event_facts(documents: Sequence[EvidenceDocument], seed: EventFacts) -> EventFacts:
    combined = "\n".join(document.text for document in documents)
    policy = classify_ai_policy(documents)
    team_max = _team_max(combined)
    divisions = _divisions(combined)
    return seed.model_copy(
        update={
            "ai_policy": policy.policy,
            "ai_policy_reason": policy.reason,
            "ai_policy_source": policy.source_url,
            "ai_policy_evidence": policy.evidence,
            "ai_policy_confidence": policy.confidence,
            "ai_policy_conflicting": policy.conflicting,
            "team_max": team_max if team_max is not None else seed.team_max,
            "divisions": divisions or seed.divisions,
            "schedule_mode": _schedule_mode(combined, seed.schedule_mode),
        }
    )
