from typing import Any, Literal

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from learning_coach.code_practice import (
    BoundedCodePracticeAgent,
    CodePracticeToolRegistry,
    DeterministicExerciseGenerator,
    RestrictedPythonExecutor,
    is_code_practice_topic,
)
from learning_coach.context import (
    LearningRuntimeContext,
    build_context_summary,
    create_learning_runtime_context,
    merge_recent_errors,
)
from learning_coach.model import LearningCoachModels
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import (
    AgentHandoff,
    Assessment,
    CodeExercise,
    CodeExerciseView,
    LearningEvent,
)
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
        else:
            model_suite = (
                models
                if isinstance(models, LearningCoachModels)
                else LearningCoachModels.from_models(models)
            )
            self.runnables = LearningCoachRunnables.from_models(model_suite)
        generator = DeterministicExerciseGenerator()
        executor = RestrictedPythonExecutor()
        self.code_practice = BoundedCodePracticeAgent(
            CodePracticeToolRegistry(generator=generator, runner=executor.run)
        )

    def make_diagnostic(self, state: LearningState) -> dict[str, Any]:
        """Generate the diagnostic question from the topic and images only.

        The node stays a pure function of its state input so the graph can
        cache and replay its update without leaking another session's context.
        """

        self._write_status("diagnostic", "started")
        diagnostic = self.runnables.diagnostic.invoke(
            {
                "topic": state["topic"],
                "diagnostic_images": state.get("diagnostic_images", []),
            }
        )
        self._write_status("diagnostic", "completed")
        return {
            "diagnostic_question": diagnostic.question,
            "diagnostic_focus": diagnostic.focus,
            "diagnostic_difficulty": diagnostic.difficulty,
        }

    def collect_diagnostic(self, state: LearningState) -> Command:
        answer = interrupt(
            {
                "kind": "diagnostic",
                "question": state["diagnostic_question"],
            }
        )
        return Command(
            goto=["teach", "prepare_practice"],
            update={"diagnostic_answer": str(answer), "attempts": 0},
        )

    def prepare_practice(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> dict[str, Any]:
        """Decide the practice kind and pre-generate the deterministic exercise.

        This node only reads the topic and the tool budget, so the graph can
        run it in parallel with ``teach`` and merge both branches at the quiz
        fan-in node.
        """

        learning_runtime = self._runtime_context(state, runtime)
        wants_code = (
            learning_runtime.tool_call_limit > 0
            and is_code_practice_topic(state["topic"])
        )
        result: dict[str, Any] = {"practice_kind": "code" if wants_code else "text"}
        exercise = None
        code_run = None
        if wants_code:
            code_run = self.code_practice.generate(
                topic=state["topic"],
                explanation="",
                tool_call_limit=learning_runtime.tool_call_limit,
            )
            exercise = code_run.exercise
        if exercise is not None:
            assert code_run is not None
            public_exercise = CodeExerciseView.from_exercise(exercise)
            self._write_event(
                {
                    "event": "code_practice",
                    "stage": "generated",
                    "exercise": public_exercise.model_dump(mode="json"),
                    "trace": [item.model_dump() for item in code_run.trace],
                }
            )
            result["code_exercise"] = exercise.model_dump(mode="json")
            result["code_tool_trace"] = [
                item.model_dump() for item in code_run.trace
            ]
            detail = f"练习类型：code · 入口函数 {exercise.entrypoint}"
        else:
            result["practice_kind"] = "text"
            detail = "练习类型：text"
        result["learning_events"] = [
            LearningEvent(
                node="prepare_practice", status="completed", detail=detail
            ).model_dump(mode="json")
        ]
        result["agent_handoffs"] = [
            AgentHandoff(
                from_agent="practice",
                to_agent="quiz",
                payload=detail,
                reason="练习准备完成，移交出题",
            ).model_dump(mode="json")
        ]
        return result

    def make_quiz(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> dict[str, Any]:
        learning_runtime = self._runtime_context(state, runtime)
        self._write_status("quiz", "started")
        exercise_payload = state.get("code_exercise")
        code_run = None
        if exercise_payload is None and (
            learning_runtime.tool_call_limit > 0
            and is_code_practice_topic(state["topic"])
        ):
            # prepare_practice did not run (direct node call); stay self-contained.
            code_run = self.code_practice.generate(
                topic=state["topic"],
                explanation=state.get("explanation", ""),
                tool_call_limit=learning_runtime.tool_call_limit,
            )
            if code_run.exercise is not None:
                exercise_payload = code_run.exercise.model_dump(mode="json")
        if exercise_payload is not None:
            exercise = CodeExercise.model_validate(exercise_payload)
            question = (
                f"{exercise.title}\n\n{exercise.instructions}\n"
                f"入口函数：{exercise.entrypoint}"
            )
            result: dict[str, Any] = {"quiz_question": question}
            if code_run is not None and code_run.exercise is not None:
                public_exercise = CodeExerciseView.from_exercise(code_run.exercise)
                self._write_event(
                    {
                        "event": "code_practice",
                        "stage": "generated",
                        "exercise": public_exercise.model_dump(mode="json"),
                        "trace": [
                            item.model_dump() for item in code_run.trace
                        ],
                    }
                )
                result["code_exercise"] = exercise_payload
                result["code_tool_trace"] = [
                    item.model_dump() for item in code_run.trace
                ]
            self._write_status("quiz", "completed")
            return result
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
        payload: dict[str, Any] = {
            "kind": "quiz",
            "question": state["quiz_question"],
        }
        if state.get("code_exercise"):
            payload["code_exercise"] = CodeExerciseView.from_exercise(
                CodeExercise.model_validate(state["code_exercise"])
            ).model_dump(mode="json")
        answer = interrupt(
            payload
        )
        return {"quiz_answer": str(answer)}

    def assess(
        self,
        state: LearningState,
        runtime: Runtime[LearningRuntimeContext] | LearningRuntimeContext | None = None,
    ) -> Command:
        learning_runtime = self._runtime_context(state, runtime)
        self._write_status("assessment", "started")
        code_exercise = state.get("code_exercise")
        code_run = None
        if code_exercise:
            exercise = CodeExercise.model_validate(code_exercise)
            code_run = self.code_practice.evaluate(
                exercise=exercise,
                code=state["quiz_answer"],
                tool_call_limit=learning_runtime.tool_call_limit,
            )
            if code_run.report is None:
                raise RuntimeError("代码实践工具没有返回执行报告。")
            report = code_run.report
            if report.status == "passed":
                feedback = "全部代码测试通过，入口函数满足当前练习要求。"
                missing_point = "已经通过全部代码测试"
            else:
                first_hint = report.hints[0].text if report.hints else "请检查实现。"
                feedback = (
                    f"通过 {report.passed_tests}/{report.total_tests} 个测试；"
                    f"错误类型：{report.error_type}。一级提示：{first_hint}"
                )
                missing_point = first_hint
            assessment = Assessment(
                score=report.score,
                feedback=feedback,
                missing_point=missing_point,
            )
            self._write_event(
                {
                    "event": "code_practice",
                    "stage": "evaluated",
                    "report": report.model_dump(mode="json"),
                    "trace": [item.model_dump() for item in code_run.trace],
                }
            )
        else:
            assessment = self.runnables.assessment.invoke(
                {
                    "topic": state["topic"],
                    "quiz_question": state["quiz_question"],
                    "quiz_answer": state["quiz_answer"],
                }
            )
        attempts = state.get("attempts", 0) + 1
        error_delta: list[str] = []
        if assessment.score < learning_runtime.target_mastery:
            error_delta = [assessment.missing_point]
        merged_errors = merge_recent_errors(
            list(state.get("recent_errors", [])), error_delta
        )
        progress = dict(state)
        progress.update(
            mastery_level=assessment.score,
            recent_errors=merged_errors,
            feedback=assessment.feedback,
        )
        update: dict[str, Any] = {
            "score": assessment.score,
            "mastery_level": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
            "recent_errors": error_delta,
            "context_summary": build_context_summary(
                progress, learning_runtime
            ),
            "attempts": attempts,
            "learning_events": [
                LearningEvent(
                    node="assess",
                    status="completed",
                    detail=f"第 {attempts} 次评价 {assessment.score} 分",
                ).model_dump(mode="json")
            ],
        }
        if code_run is not None and code_run.report is not None:
            update["code_practice_report"] = code_run.report.model_dump(mode="json")
            update["code_tool_trace"] = [
                item.model_dump() for item in code_run.trace
            ]
        self._write_status("assessment", "completed")
        route = route_after_assessment(
            {"score": assessment.score, "attempts": attempts}
        )
        goto: Any = (
            ["teach", "prepare_practice"] if route == "retry" else "summarize"
        )
        return Command(goto=goto, update=update)

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
