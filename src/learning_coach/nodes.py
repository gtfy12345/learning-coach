from typing import Any, Literal

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from learning_coach.context import (
    LearningRuntimeContext,
    build_context_summary,
    create_learning_runtime_context,
    update_recent_errors,
)
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

    def make_diagnostic(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> dict[str, Any]:
        learning_runtime = self._runtime_context(state, runtime)
        self._write_status("diagnostic", "started")
        diagnostic = self.runnables.diagnostic.invoke(
            {
                "topic": state["topic"],
                "diagnostic_images": state.get("diagnostic_images", []),
            }
        )
        result = {
            "learning_goal": learning_runtime.learning_goal,
            "mastery_level": state.get("mastery_level", 0),
            "recent_errors": list(state.get("recent_errors", [])),
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

    def teach(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> dict[str, Any]:
        learning_runtime = self._runtime_context(state, runtime)
        task_input = {
            "topic": state["topic"],
            "diagnostic_focus": state.get("diagnostic_focus", "暂无"),
            "diagnostic_difficulty": state.get("diagnostic_difficulty", "暂无"),
            "diagnostic_answer": state.get("diagnostic_answer", "暂无"),
            "feedback": state.get("feedback", "暂无"),
            "missing_point": state.get("missing_point", "暂无"),
            "study_material": state.get("study_material", ""),
            "study_chunks": state.get("study_chunks", []),
            "learning_goal": learning_runtime.learning_goal,
            "mastery_level": state.get("mastery_level", 0),
            "recent_errors": state.get("recent_errors", []),
            "context_summary": state.get("context_summary", ""),
        }
        self._write_status("teaching", "started")
        text_parts: list[str] = []
        sources: list[Any] = []
        context_report: Any = None
        retrieval_report: Any = None
        graph_report: Any = None
        for teaching in self.runnables.teach_stream(
            task_input, learning_runtime
        ):
            if (
                teaching.retrieval_report is not None
                and retrieval_report is None
            ):
                retrieval_report = teaching.retrieval_report
                self._write_event(
                    {
                        "event": "retrieval",
                        "task": "teaching",
                        "report": retrieval_report.model_dump(),
                    }
                )
            if teaching.graph_report is not None and graph_report is None:
                graph_report = teaching.graph_report
                self._write_event(
                    {
                        "event": "knowledge_graph",
                        "task": "teaching",
                        "report": graph_report.model_dump(),
                    }
                )
            if teaching.sources and not sources:
                sources = list(teaching.sources)
                self._write_event(
                    {
                        "event": "sources",
                        "task": "teaching",
                        "sources": [source.model_dump() for source in sources],
                    }
                )
            if teaching.context_report is not None and context_report is None:
                context_report = teaching.context_report
            if teaching.text:
                text_parts.append(teaching.text)
                self._write_token("teaching", teaching.text)
        self._write_status("teaching", "completed")
        result: dict[str, Any] = {
            "explanation": "".join(text_parts),
            "explanation_sources": [
                source.model_dump() for source in sources
            ],
            "context_summary": state.get("context_summary")
            or build_context_summary(state, learning_runtime),
        }
        if context_report is not None:
            result["context_report"] = context_report.model_dump()
        if retrieval_report is not None:
            result["retrieval_report"] = retrieval_report.model_dump()
        if graph_report is not None:
            result["graph_report"] = graph_report.model_dump()
        return result

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

    def assess(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> dict[str, Any]:
        learning_runtime = self._runtime_context(state, runtime)
        self._write_status("assessment", "started")
        assessment = self.runnables.assessment.invoke(
            {
                "topic": state["topic"],
                "quiz_question": state["quiz_question"],
                "quiz_answer": state["quiz_answer"],
            }
        )
        recent_errors = list(state.get("recent_errors", []))
        if assessment.score < learning_runtime.target_mastery:
            recent_errors = update_recent_errors(
                recent_errors, assessment.missing_point
            )
        progress = dict(state)
        progress.update(
            mastery_level=assessment.score,
            recent_errors=recent_errors,
            feedback=assessment.feedback,
        )
        result = {
            "score": assessment.score,
            "mastery_level": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
            "recent_errors": recent_errors,
            "context_summary": build_context_summary(
                progress, learning_runtime
            ),
            "attempts": state.get("attempts", 0) + 1,
        }
        self._write_status("assessment", "completed")
        return result

    @staticmethod
    def _runtime_context(
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None,
    ) -> LearningRuntimeContext:
        if isinstance(runtime, LearningRuntimeContext):
            return runtime
        runtime_context = getattr(runtime, "context", None)
        if isinstance(runtime_context, LearningRuntimeContext):
            return runtime_context
        return create_learning_runtime_context(
            state["topic"], learning_goal=state.get("learning_goal")
        )

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
