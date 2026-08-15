from flagwatch.analysis.evidence import EvidenceDocument
from flagwatch.analysis.facts import extract_event_facts
from flagwatch.domain import EventFacts, ScheduleMode


def test_extracts_team_divisions_and_staggered_schedule():
    documents = [
        EvidenceDocument(
            "https://ctf.example/rules",
            "Teams can include up to 6 members. Divisions: Student, Open. "
            "Teams receive staggered start times.",
        )
    ]

    facts = extract_event_facts(documents, EventFacts())

    assert facts.team_max == 6
    assert facts.divisions == ["Student", "Open"]
    assert facts.schedule_mode is ScheduleMode.STAGGERED


def test_detects_multi_stage_without_overwriting_seed_prize():
    seed = EventFacts(prize_summary="$1,000 total")
    documents = [
        EvidenceDocument(
            "https://ctf.example/about",
            "The online qualification round is followed by an in-person final stage.",
        )
    ]

    facts = extract_event_facts(documents, seed)

    assert facts.schedule_mode is ScheduleMode.MULTI_STAGE
    assert facts.prize_summary == "$1,000 total"
