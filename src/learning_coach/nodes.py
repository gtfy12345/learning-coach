from typing import Any, Literal

from langgraph.config import get_stream_writer
from langgraph.types import interrupt

from learning_coach.model import LearningCoachModels
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import GroundedTeaching
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
        self._write_status("diagnostic", "started")
        diagnostic = self.runnables.diagnostic.invoke(
            {
                "topic": state["topic"],
                "diagnostic_images": state.get("diagnostic_images", []),
            }
        )
        result = {
            "diagnostic_question": diagnostic.question,
            "diagnostic_focus": diagnostic.focus,
            "diagnostic_difficulty": diagnostic.difficulty,
        }
        self._write_status("diagnostic", "completed")
        return result

    def collect_diagnostic(self, state: LearningState) -> dict[str, Any]:
        answer = interrupt(
            {
                "kind": "diagnostic",
                "question": state["diagnostic_question"],
            }
        )
        return {"diagnostic_answer": str(answer), "attempts": 0}

    def teach(self, state: LearningState) -> dict[str, str]:
        task_input = {
            "topic": state["topic"],
            "diagnostic_focus": state.get("diagnostic_focus", "暂无"),
            "diagnostic_difficulty": state.get("diagnostic_difficulty", "暂无"),
            "diagnostic_answer": state.get("diagnostic_answer", "暂无"),
            "feedback": state.get("feedback", "暂无"),
            "missing_point": state.get("missing_point", "暂无"),
            "study_material": state.get("study_material", ""),
        }
        self._write_status("teaching", "started")
        text_parts: list[str] = []
        sources: list[Any] = []
        for chunk in self.runnables.teaching.stream(task_input):
            teaching = (
                chunk
                if isinstance(chunk, GroundedTeaching)
                else GroundedTeaching.model_validate(chunk)
            )
            if teaching.sources and not sources:
                sources = teaching.sources
                self._write_event(
                    {
                        "event": "sources",
                        "task": "teaching",
                        "sources": [source.model_dump() for source in sources],
                    }
                )
            if teaching.text:
                text_parts.append(teaching.text)
                self._write_token("teaching", teaching.text)
        self._write_status("teaching", "completed")
        return {
            "explanation": "".join(text_parts),
            "explanation_sources": [
                source.model_dump() for source in sources
            ],
        }

    def make_quiz(self, state: LearningState) -> dict[str, str]:
        self._write_status("quiz", "started")
        parts = self.runnables.quiz.stream(
            {
                "topic": state["topic"],
                "explanation": state["explanation"],
            }
        )
        question_parts: list[str] = []
        for part in parts:
            text = str(part)
            question_parts.append(text)
            self._write_token("quiz", text)
        question = "".join(question_parts)
        self._write_status("quiz", "completed")
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
        self._write_status("assessment", "started")
        assessment = self.runnables.assessment.invoke(
            {
                "topic": state["topic"],
                "quiz_question": state["quiz_question"],
                "quiz_answer": state["quiz_answer"],
            }
        )
        result = {
            "score": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
            "attempts": state.get("attempts", 0) + 1,
        }
        self._write_status("assessment", "completed")
        return result

    def summarize(self, state: LearningState) -> dict[str, str]:
        self._write_status("summary", "started")
        parts = self.runnables.summary.stream(
            {
                "topic": state["topic"],
                "score": state["score"],
                "feedback": state["feedback"],
                "missing_point": state["missing_point"],
            }
        )
        summary_parts: list[str] = []
        for part in parts:
            text = str(part)
            summary_parts.append(text)
            self._write_token("summary", text)
        summary = "".join(summary_parts)
        self._write_status("summary", "completed")
        return {"summary": summary}

    @staticmethod
    def _write_event(event: dict[str, Any]) -> None:
        try:
            writer = get_stream_writer()
        except RuntimeError:
            return
        writer(event)

    @classmethod
    def _write_status(cls, task: str, status: str) -> None:
        cls._write_event({"event": "status", "task": task, "status": status})

    @classmethod
    def _write_token(cls, task: str, text: str) -> None:
        if text:
            cls._write_event({"event": "token", "task": task, "text": text})
