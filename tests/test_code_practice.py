from typing import Any

import pytest
from pydantic import ValidationError

from learning_coach.code_practice import (
    CodePracticeToolRegistry,
    DeterministicExerciseGenerator,
    is_code_practice_topic,
)
from learning_coach.schemas import (
    CodeExercise,
    CodePracticeReport,
    CodeTestCase,
    GenerateCodeExerciseInput,
    RunCodeTestsInput,
)


def test_code_practice_schemas_reject_unknown_and_oversized_values() -> None:
    test = CodeTestCase(
        test_id="zero",
        args=[0],
        expected=0,
        visible=True,
    )
    exercise = CodeExercise(
        exercise_id="a" * 64,
        title="限制分数范围",
        instructions="实现 clamp_score(score)。",
        entrypoint="clamp_score",
        starter_code="def clamp_score(score):\n    pass\n",
        difficulty="foundation",
        tests=[test],
    )

    assert exercise.tests[0].expected == 0
    with pytest.raises(ValidationError):
        GenerateCodeExerciseInput.model_validate(
            {"topic": "Python", "unexpected": True}
        )
    with pytest.raises(ValidationError):
        RunCodeTestsInput(exercise=exercise, code="x" * 20_001)


def test_deterministic_generator_returns_stable_bounded_python_exercise() -> None:
    generator = DeterministicExerciseGenerator()

    first = generator.generate("Python 函数", "把输入分数限制在 0 到 100。")
    second = generator.generate("Python 函数", "把输入分数限制在 0 到 100。")

    assert first is not None
    assert first == second
    assert first.entrypoint == "clamp_score"
    assert first.exercise_id == second.exercise_id
    assert 2 <= len(first.tests) <= 12
    assert all(len(case.test_id) <= 64 for case in first.tests)


def test_non_code_topic_keeps_text_practice_path() -> None:
    generator = DeterministicExerciseGenerator()

    assert is_code_practice_topic("概念图中的前置关系") is False
    assert generator.generate("概念图中的前置关系", "解释定义") is None


def test_registry_selects_only_the_tool_allowed_for_current_stage() -> None:
    generator = DeterministicExerciseGenerator()

    def fake_runner(exercise: CodeExercise, code: str) -> CodePracticeReport:
        return CodePracticeReport(
            status="passed",
            error_type="none",
            passed_tests=len(exercise.tests),
            total_tests=len(exercise.tests),
            score=100,
            outcomes=[],
            hints=[],
            safety_notice="local restricted executor",
        )

    registry = CodePracticeToolRegistry(generator=generator, runner=fake_runner)
    exercise = generator.generate("Python 函数")
    assert exercise is not None

    assert [tool.name for tool in registry.available_tools(
        stage="generate", exercise=None, tool_call_limit=1
    )] == ["generate_code_exercise"]
    assert [tool.name for tool in registry.available_tools(
        stage="evaluate", exercise=exercise, tool_call_limit=1
    )] == ["run_code_tests"]
    assert registry.available_tools(
        stage="evaluate", exercise=None, tool_call_limit=1
    ) == []
    assert registry.available_tools(
        stage="generate", exercise=None, tool_call_limit=0
    ) == []


def test_tool_input_schema_is_applied_before_runner_invocation() -> None:
    calls: list[tuple[CodeExercise, str]] = []
    generator = DeterministicExerciseGenerator()

    def fake_runner(exercise: CodeExercise, code: str) -> CodePracticeReport:
        calls.append((exercise, code))
        return CodePracticeReport(
            status="passed",
            error_type="none",
            passed_tests=len(exercise.tests),
            total_tests=len(exercise.tests),
            score=100,
            outcomes=[],
            hints=[],
            safety_notice="local restricted executor",
        )

    registry = CodePracticeToolRegistry(generator=generator, runner=fake_runner)
    exercise = generator.generate("Python 函数")
    assert exercise is not None
    tool = registry.available_tools(
        stage="evaluate", exercise=exercise, tool_call_limit=1
    )[0]

    result: dict[str, Any] = tool.invoke(
        {"exercise": exercise.model_dump(), "code": "def clamp_score(score): return score"}
    )

    assert result["status"] == "passed"
    assert calls == [(exercise, "def clamp_score(score): return score")]
    with pytest.raises(ValidationError):
        tool.invoke(
            {
                "exercise": exercise.model_dump(),
                "code": "def clamp_score(score): return score",
                "unknown": True,
            }
        )
