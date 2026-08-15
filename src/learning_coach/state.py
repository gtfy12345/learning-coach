from typing import Annotated, Any, TypedDict

from learning_coach.context import merge_recent_errors

MAX_LEARNING_EVENTS = 30
MAX_TEACHING_REVIEWS = 9
MAX_AGENT_HANDOFFS = 20
MAX_RESEARCH_FINDINGS = 6


def append_learning_events(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: merge events from parallel branches and keep the latest slice."""

    merged = [*existing, *(updates or [])]
    return merged[-MAX_LEARNING_EVENTS:]


def append_teaching_reviews(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: merge parallel review findings and keep the latest slice."""

    merged = [*existing, *(updates or [])]
    return merged[-MAX_TEACHING_REVIEWS:]


def append_agent_handoffs(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: merge agent handoff traces and keep the latest slice."""

    merged = [*existing, *(updates or [])]
    return merged[-MAX_AGENT_HANDOFFS:]


def append_research_findings(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: merge per-focus research findings inside the teaching swarm."""

    merged = [*existing, *(updates or [])]
    return merged[-MAX_RESEARCH_FINDINGS:]


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
    learning_goal: str
    learner_id: str
    long_term_memory: dict[str, Any]
    execution_approved: bool
    mastery_level: int
    recent_errors: Annotated[list[str], merge_recent_errors]
    learning_events: Annotated[
        list[dict[str, Any]], append_learning_events
    ]
    practice_kind: str
    teaching_plan: dict[str, Any]
    research_evidence: dict[str, Any]
    teaching_reviews: Annotated[
        list[dict[str, Any]], append_teaching_reviews
    ]
    agent_handoffs: Annotated[list[dict[str, Any]], append_agent_handoffs]
    context_summary: str
    context_report: dict[str, Any]
    diagnostic_images: list[dict[str, Any]]
    study_material: str
    study_chunks: list[dict[str, Any]]
    ingestion_report: dict[str, Any]
    retrieval_report: dict[str, Any]
    graph_report: dict[str, Any]
    diagnostic_question: str
    diagnostic_focus: str
    diagnostic_difficulty: str
    diagnostic_answer: str
    explanation: str
    explanation_sources: list[dict[str, Any]]
    quiz_question: str
    code_exercise: dict[str, Any]
    code_practice_report: dict[str, Any]
    code_tool_trace: list[dict[str, Any]]
    quiz_answer: str
    score: int
    feedback: str
    missing_point: str
    attempts: int
    summary: str
