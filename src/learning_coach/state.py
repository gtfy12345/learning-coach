from typing import Any, TypedDict


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
    diagnostic_images: list[dict[str, Any]]
    diagnostic_question: str
    diagnostic_focus: str
    diagnostic_difficulty: str
    diagnostic_answer: str
    explanation: str
    quiz_question: str
    quiz_answer: str
    score: int
    feedback: str
    missing_point: str
    attempts: int
    summary: str
