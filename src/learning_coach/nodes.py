from typing import Any, Literal

from langgraph.types import interrupt

from learning_coach.model import LearningCoachModels
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.state import LearningState


def route_after_assessment(state: LearningState) -> Literal["retry", "finish"]:
    """Choose a bounded retry so the graph cannot loop forever."""

    if state["score"] >= 80 or state.get("attempts", 0) >= 2:
        return "finish"
    return "retry"


class LearningCoachNodes:
    """Nodes that perform one learning task and return partial state updates."""

    def __init__(self, models: LearningCoachModels | Any) -> None:
        if isinstance(models, LearningCoachRunnables):
            self.runnables = models
            return
        model_suite = (
            models
            if isinstance(models, LearningCoachModels)
            else LearningCoachModels.from_models(models)
        )
        self.runnables = LearningCoachRunnables.from_models(model_suite)

    def make_diagnostic(self, state: LearningState) -> dict[str, str]:
        diagnostic = self.runnables.diagnostic.invoke(
            {
                "topic": state["topic"],
                "diagnostic_images": state.get("diagnostic_images", []),
            }
        )
        return {
            "diagnostic_question": diagnostic.question,
            "diagnostic_focus": diagnostic.focus,
            "diagnostic_difficulty": diagnostic.difficulty,
        }

    def collect_diagnostic(self, state: LearningState) -> dict[str, Any]:
        answer = interrupt(
            {
                "kind": "diagnostic",
                "question": state["diagnostic_question"],
            }
        )
        return {"diagnostic_answer": str(answer), "attempts": 0}

    def teach(self, state: LearningState) -> dict[str, str]:
        explanation = self.runnables.teaching.invoke(
            {
                "topic": state["topic"],
                "diagnostic_focus": state.get("diagnostic_focus", "暂无"),
                "diagnostic_difficulty": state.get(
                    "diagnostic_difficulty", "暂无"
                ),
                "diagnostic_answer": state.get("diagnostic_answer", "暂无"),
                "feedback": state.get("feedback", "暂无"),
                "missing_point": state.get("missing_point", "暂无"),
            }
        )
        return {"explanation": explanation}

    def make_quiz(self, state: LearningState) -> dict[str, str]:
        question = self.runnables.quiz.invoke(
            {
                "topic": state["topic"],
                "explanation": state["explanation"],
            }
        )
        return {"quiz_question": question}

    def collect_quiz(self, state: LearningState) -> dict[str, str]:
        answer = interrupt(
            {
                "kind": "quiz",
                "question": state["quiz_question"],
            }
        )
        return {"quiz_answer": str(answer)}

    def assess(self, state: LearningState) -> dict[str, Any]:
        assessment = self.runnables.assessment.invoke(
            {
                "topic": state["topic"],
                "quiz_question": state["quiz_question"],
                "quiz_answer": state["quiz_answer"],
            }
        )
        return {
            "score": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
            "attempts": state.get("attempts", 0) + 1,
        }

    def summarize(self, state: LearningState) -> dict[str, str]:
        summary = self.runnables.summary.invoke(
            {
                "topic": state["topic"],
                "score": state["score"],
                "feedback": state["feedback"],
                "missing_point": state["missing_point"],
            }
        )
        return {"summary": summary}
