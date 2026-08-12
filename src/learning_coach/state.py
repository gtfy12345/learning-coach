from typing import Any, TypedDict


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
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
