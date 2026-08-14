from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import json

from langchain_core.tools import BaseTool, StructuredTool

from learning_coach.schemas import (
    CodeDifficulty,
    CodeExercise,
    CodePracticeReport,
    CodeTestCase,
    GenerateCodeExerciseInput,
    RunCodeTestsInput,
)


_CODE_TOPIC_MARKERS = (
    "python",
    "代码",
    "编程",
    "函数",
    "algorithm",
    "算法",
)


def is_code_practice_topic(topic: str, explanation: str = "") -> bool:
    """Return whether the learner explicitly requested a coding topic."""

    haystack = f"{topic}\n{explanation}".casefold()
    return any(marker in haystack for marker in _CODE_TOPIC_MARKERS)


class DeterministicExerciseGenerator:
    """Generate a stable, executable Python function exercise."""

    def generate(
        self,
        topic: str,
        explanation: str = "",
        difficulty: CodeDifficulty = "application",
    ) -> CodeExercise | None:
        request = GenerateCodeExerciseInput(
            topic=topic,
            explanation=explanation,
            difficulty=difficulty,
        )
        if not is_code_practice_topic(request.topic, request.explanation):
            return None
        if any(
            marker in f"{request.topic}\n{request.explanation}".casefold()
            for marker in ("列表", "list", "去重", "deduplicate")
        ):
            title = "保持顺序去重"
            instructions = (
                "实现 deduplicate(items)，返回保持首次出现顺序的新列表。"
                "不要修改输入列表。"
            )
            entrypoint = "deduplicate"
            starter_code = "def deduplicate(items):\n    # 在这里完成实现\n    pass\n"
            tests = [
                CodeTestCase(test_id="empty", args=[[]], expected=[], visible=True),
                CodeTestCase(
                    test_id="repeated",
                    args=[[1, 2, 1, 3, 2]],
                    expected=[1, 2, 3],
                    visible=True,
                ),
                CodeTestCase(
                    test_id="strings",
                    args=[["a", "a", "b"]],
                    expected=["a", "b"],
                ),
            ]
        else:
            title = "限制分数范围"
            instructions = (
                "实现 clamp_score(score)：小于 0 时返回 0，大于 100 时返回 100，"
                "其余值原样返回。"
            )
            entrypoint = "clamp_score"
            starter_code = "def clamp_score(score):\n    # 在这里完成实现\n    pass\n"
            tests = [
                CodeTestCase(test_id="below", args=[-5], expected=0, visible=True),
                CodeTestCase(test_id="middle", args=[72], expected=72, visible=True),
                CodeTestCase(test_id="above", args=[120], expected=100),
                CodeTestCase(test_id="lower_bound", args=[0], expected=0),
            ]
        fingerprint = json.dumps(
            {
                "entrypoint": entrypoint,
                "tests": [test.model_dump(mode="json") for test in tests],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return CodeExercise(
            exercise_id=sha256(fingerprint.encode("utf-8")).hexdigest(),
            title=title,
            instructions=instructions,
            entrypoint=entrypoint,
            starter_code=starter_code,
            difficulty=request.difficulty,
            tests=tests,
        )


CodeRunner = Callable[[CodeExercise, str], CodePracticeReport]


class CodePracticeToolRegistry:
    """Expose only the code-practice tool allowed by the current stage."""

    def __init__(
        self,
        *,
        generator: DeterministicExerciseGenerator,
        runner: CodeRunner,
    ) -> None:
        self.generator = generator
        self.runner = runner
        self._generate_tool = StructuredTool.from_function(
            func=self._generate,
            name="generate_code_exercise",
            description="Generate one bounded Python function exercise.",
            args_schema=GenerateCodeExerciseInput,
        )
        self._test_tool = StructuredTool.from_function(
            func=self._run_tests,
            name="run_code_tests",
            description="Run server-owned tests with the restricted local executor.",
            args_schema=RunCodeTestsInput,
        )

    def available_tools(
        self,
        *,
        stage: str,
        exercise: CodeExercise | None,
        tool_call_limit: int,
    ) -> list[BaseTool]:
        if tool_call_limit <= 0:
            return []
        if stage == "generate" and exercise is None:
            return [self._generate_tool]
        if stage == "evaluate" and exercise is not None:
            return [self._test_tool]
        return []

    def _generate(
        self,
        topic: str,
        explanation: str = "",
        difficulty: CodeDifficulty = "application",
    ) -> dict[str, object] | None:
        exercise = self.generator.generate(topic, explanation, difficulty)
        return exercise.model_dump(mode="json") if exercise is not None else None

    def _run_tests(
        self,
        exercise: CodeExercise,
        code: str,
    ) -> dict[str, object]:
        report = self.runner(exercise, code)
        return report.model_dump(mode="json")
