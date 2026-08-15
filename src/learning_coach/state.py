from typing import Any, TypedDict


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
    learning_goal: str
    mastery_level: int
    recent_errors: list[str]
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
