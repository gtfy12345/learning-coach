from typing import Any

import pytest
from pydantic import ValidationError

import learning_coach.code_practice as code_practice_module
from learning_coach.code_practice import (
    BoundedCodePracticeAgent,
    CodePracticeToolRegistry,
    DeterministicExerciseGenerator,
    RestrictedPythonExecutor,
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


@pytest.fixture
def python_exercise() -> CodeExercise:
    exercise = DeterministicExerciseGenerator().generate("Python 函数")
    assert exercise is not None
    return exercise


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        ("import os\ndef clamp_score(score): return score", "Import"),
        ("def clamp_score(score): return open('x')", "open"),
        ("def clamp_score(score): return score.__class__", "dunder"),
    ],
)
def test_restricted_executor_rejects_dangerous_ast_before_running(
    python_exercise: CodeExercise,
    code: str,
    fragment: str,
) -> None:
    report = RestrictedPythonExecutor().run(python_exercise, code)

    assert report.status == "rejected"
    assert report.error_type == "policy_violation"
    assert fragment.casefold() in report.outcomes[0].summary.casefold()
    assert "/Users/" not in report.model_dump_json()


def test_restricted_executor_runs_server_owned_tests(
    python_exercise: CodeExercise,
) -> None:
    report = RestrictedPythonExecutor().run(
        python_exercise,
        "def clamp_score(score):\n    return min(100, max(0, score))\n",
    )

    assert report.status == "passed"
    assert report.error_type == "none"
    assert report.passed_tests == report.total_tests == 4
    assert report.score == 100
    assert all(outcome.status == "passed" for outcome in report.outcomes)


def test_restricted_executor_terminates_infinite_loop(
    python_exercise: CodeExercise,
) -> None:
    report = RestrictedPythonExecutor(timeout_seconds=0.25).run(
        python_exercise,
        "def clamp_score(score):\n    while True:\n        pass\n",
    )

    assert report.status == "error"
    assert report.error_type == "timeout"
    assert report.score == 0
    assert report.total_tests == 4


def test_bounded_react_agent_generates_and_evaluates_with_trace(
    python_exercise: CodeExercise,
) -> None:
    executor = RestrictedPythonExecutor()
    registry = CodePracticeToolRegistry(
        generator=DeterministicExerciseGenerator(),
        runner=executor.run,
    )
    agent = BoundedCodePracticeAgent(registry)

    generated = agent.generate(
        topic="Python 函数",
        explanation="限制输入范围",
        tool_call_limit=2,
    )
    evaluated = agent.evaluate(
        exercise=python_exercise,
        code="def clamp_score(score): return min(100, max(0, score))",
        tool_call_limit=2,
    )

    assert generated.exercise is not None
    assert generated.tool_calls == 1
    assert generated.trace[0].tool_name == "generate_code_exercise"
    assert generated.termination_reason == "completed"
    assert evaluated.report is not None
    assert evaluated.report.status == "passed"
    assert evaluated.trace[0].observation == "4/4 tests passed"


def test_bounded_react_agent_stops_on_duplicate_action_and_budget() -> None:
    registry = CodePracticeToolRegistry(
        generator=DeterministicExerciseGenerator(),
        runner=RestrictedPythonExecutor().run,
    )
    agent = BoundedCodePracticeAgent(registry)
    action = {
        "tool_name": "generate_code_exercise",
        "arguments": {"topic": "历史概念", "explanation": "纯理论"},
    }

    duplicate = agent.run(
        stage="generate",
        actions=[action, action],
        exercise=None,
        tool_call_limit=3,
    )
    exhausted = agent.generate(
        topic="Python 函数", explanation="", tool_call_limit=0
    )

    assert duplicate.tool_calls == 1
    assert duplicate.termination_reason == "duplicate_action"
    assert duplicate.trace[-1].status == "rejected"
    assert exhausted.tool_calls == 0
    assert exhausted.termination_reason == "budget_exhausted"


@pytest.mark.parametrize(
    ("code", "error_type"),
    [
        ("def clamp_score(score)\n    return score", "syntax_error"),
        ("def clamp_score(score): return 1 / 0", "runtime_error"),
        ("def clamp_score(score): return score", "test_failure"),
    ],
)
def test_executor_classifies_errors_and_returns_three_hint_levels(
    python_exercise: CodeExercise,
    code: str,
    error_type: str,
) -> None:
    report = RestrictedPythonExecutor().run(python_exercise, code)

    assert report.error_type == error_type
    assert [hint.level for hint in report.hints] == [1, 2, 3]
    assert all(hint.error_type == error_type for hint in report.hints)
    assert "def clamp_score(score): return min" not in report.model_dump_json()


def test_failed_tests_produce_deterministic_partial_score_and_safe_detail(
    python_exercise: CodeExercise,
) -> None:
    report = RestrictedPythonExecutor().run(
        python_exercise,
        "def clamp_score(score):\n    return max(0, score)\n",
    )

    assert report.error_type == "test_failure"
    assert report.passed_tests == 3
    assert report.total_tests == 4
    assert report.score == 75
    assert report.outcomes[2].summary == "output mismatch in hidden test"
    assert "120" not in report.outcomes[2].summary


def test_missing_runner_result_is_classified_as_resource_limit(
    monkeypatch: pytest.MonkeyPatch,
    python_exercise: CodeExercise,
) -> None:
    class Completed:
        stdout = ""
        stderr = "killed"
        returncode = -9

    monkeypatch.setattr(
        code_practice_module.subprocess,
        "run",
        lambda *args, **kwargs: Completed(),
    )

    report = RestrictedPythonExecutor().run(
        python_exercise,
        "def clamp_score(score): return score",
    )

    assert report.error_type == "resource_limit"
    assert report.status == "error"
    assert [hint.level for hint in report.hints] == [1, 2, 3]
    assert "killed" not in report.model_dump_json()
