from typing import TypedDict


class LearningState(TypedDict, total=False):
    """The explicit state shared by every node in the learning workflow."""

    topic: str
    diagnostic_question: str
    diagnostic_answer: str
    explanation: str
    quiz_question: str
    quiz_answer: str
    score: int
    feedback: str
    missing_point: str
    attempts: int
    summary: str
