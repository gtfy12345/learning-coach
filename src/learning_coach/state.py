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
    diagnostic_question: str
    diagnostic_focus: str
    diagnostic_difficulty: str
    diagnostic_answer: str
    explanation: str
    explanation_sources: list[dict[str, Any]]
    quiz_question: str
    quiz_answer: str
    score: int
    feedback: str
    missing_point: str
    attempts: int
    summary: str
