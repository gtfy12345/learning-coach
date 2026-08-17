from collections.abc import Mapping
from typing import Annotated, Any, Literal, TypedDict

from learning_coach.context import merge_recent_errors

MAX_LEARNING_EVENTS = 30
MAX_TEACHING_REVIEWS = 9
MAX_AGENT_HANDOFFS = 20
MAX_RESEARCH_FINDINGS = 6
MAX_SAFETY_FINDINGS = 10

LearningMode = Literal["teach_first", "diagnose_first"]
DEFAULT_LEARNING_MODE: LearningMode = "teach_first"
LEGACY_LEARNING_MODE: LearningMode = "diagnose_first"
_LEARNING_MODES = frozenset({DEFAULT_LEARNING_MODE, LEGACY_LEARNING_MODE})


def learning_mode_for_new_session(value: str | None) -> LearningMode:
    """Normalize an explicit mode while keeping the new teach-first default."""

    normalized = (value or DEFAULT_LEARNING_MODE).strip().lower()
    if not normalized:
        normalized = DEFAULT_LEARNING_MODE
    if normalized not in _LEARNING_MODES:
        choices = ", ".join(sorted(_LEARNING_MODES))
        raise ValueError(f"learning_mode 必须是以下值之一：{choices}。")
    return normalized  # type: ignore[return-value]


def learning_mode_for_state(state: Mapping[str, Any]) -> LearningMode:
    """Resolve persisted state, preserving legacy diagnose-first checkpoints."""

    value = state.get("learning_mode")
    if value is None:
        return LEGACY_LEARNING_MODE
    return learning_mode_for_new_session(str(value))


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


def append_safety_findings(
    existing: list[dict[str, Any]], updates: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Reducer: merge PII/injection findings and keep the latest slice."""

    merged = [*existing, *(updates or [])]
    return merged[-MAX_SAFETY_FINDINGS:]


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
    learning_mode: LearningMode
    initial_lesson: str
    understanding_check: dict[str, Any]
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
    safety_findings: Annotated[list[dict[str, Any]], append_safety_findings]
    stage_report: dict[str, Any]
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
