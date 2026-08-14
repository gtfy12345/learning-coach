from __future__ import annotations

import ast
import base64
from collections.abc import Callable
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from learning_coach.schemas import (
    CodeDifficulty,
    CodeExercise,
    CodePracticeRun,
    CodePracticeReport,
    CodeTestCase,
    CodeTestOutcome,
    GenerateCodeExerciseInput,
    RunCodeTestsInput,
    ToolTraceEntry,
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

_SAFETY_NOTICE = (
    "本地受限执行器提供纵深防护，但不是用于恶意代码或多租户的强隔离沙箱。"
)
_RESULT_MARKER = "__LEARNING_COACH_RESULT__="
_DANGEROUS_CALLS = {
    "breakpoint",
    "compile",
    "delattr",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "print",
    "setattr",
    "vars",
    "__import__",
}
_FORBIDDEN_NODES = (
    ast.AsyncFunctionDef,
    ast.Await,
    ast.ClassDef,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Nonlocal,
    ast.Yield,
    ast.YieldFrom,
)


def _policy_violation(tree: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            return f"禁止使用 {type(node).__name__}。"
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return "禁止访问 dunder 名称。"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return "禁止访问 dunder 或私有属性。"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _DANGEROUS_CALLS
        ):
            return f"禁止调用 {node.func.id}。"
    return None


def _error_report(
    exercise: CodeExercise,
    *,
    status: str,
    error_type: str,
    summary: str,
    test_id: str,
) -> CodePracticeReport:
    return CodePracticeReport(
        status=status,
        error_type=error_type,
        passed_tests=0,
        total_tests=len(exercise.tests),
        score=0,
        outcomes=[
            CodeTestOutcome(
                test_id=test_id,
                status="error",
                summary=summary[:512],
            )
        ],
        hints=[],
        safety_notice=_SAFETY_NOTICE,
    )


def _runner_source(payload: str) -> str:
    return f'''import base64
import json
import time

PAYLOAD = {payload!r}
data = json.loads(base64.b64decode(PAYLOAD).decode("utf-8"))
safe_builtins = {{
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "Exception": Exception, "float": float,
    "int": int, "len": len, "list": list, "max": max, "min": min,
    "range": range, "reversed": reversed, "round": round, "set": set,
    "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "TypeError": TypeError, "ValueError": ValueError, "zip": zip,
}}
namespace = {{"__builtins__": safe_builtins}}
outcomes = []
try:
    exec(compile(data["code"], "<learner>", "exec"), namespace, namespace)
    function = namespace.get(data["entrypoint"])
    if not callable(function):
        raise TypeError("entrypoint is not callable")
    for case in data["tests"]:
        started = time.perf_counter()
        try:
            actual = function(*case["args"])
            passed = actual == case["expected"]
            if passed:
                summary = "test passed"
                status = "passed"
            elif case["visible"]:
                summary = "expected " + repr(case["expected"])[:120] + " but got " + repr(actual)[:120]
                status = "failed"
            else:
                summary = "output mismatch in hidden test"
                status = "failed"
        except BaseException as exc:
            status = "error"
            summary = type(exc).__name__ + " while running test"
        outcomes.append({{
            "test_id": case["test_id"],
            "status": status,
            "visible": case["visible"],
            "summary": summary,
            "duration_ms": min(10000, int((time.perf_counter() - started) * 1000)),
        }})
    print({_RESULT_MARKER!r} + json.dumps({{"outcomes": outcomes}}, separators=(",", ":")))
except BaseException as exc:
    print({_RESULT_MARKER!r} + json.dumps({{
        "runner_error": type(exc).__name__ + " before tests"
    }}, separators=(",", ":")))
'''


def _set_resource_limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    except (ImportError, OSError, ValueError):
        return


class RestrictedPythonExecutor:
    """Run single-function Python exercises with bounded local defenses."""

    def __init__(self, *, timeout_seconds: float = 1.5) -> None:
        if not 0.05 <= timeout_seconds <= 5:
            raise ValueError("timeout_seconds 必须在 0.05 到 5 秒之间。")
        self.timeout_seconds = timeout_seconds

    def run(self, exercise: CodeExercise, code: str) -> CodePracticeReport:
        request = RunCodeTestsInput(exercise=exercise, code=code)
        try:
            tree = ast.parse(request.code, filename="<learner>", mode="exec")
        except SyntaxError as exc:
            line = exc.lineno or 1
            return _error_report(
                exercise,
                status="rejected",
                error_type="syntax_error",
                summary=f"SyntaxError near line {line}.",
                test_id="syntax",
            )
        violation = _policy_violation(tree)
        if violation is not None:
            return _error_report(
                exercise,
                status="rejected",
                error_type="policy_violation",
                summary=violation,
                test_id="policy",
            )

        payload = base64.b64encode(
            json.dumps(
                {
                    "code": request.code,
                    "entrypoint": exercise.entrypoint,
                    "tests": [case.model_dump(mode="json") for case in exercise.tests],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).decode("ascii")
        try:
            with tempfile.TemporaryDirectory(prefix="learning-coach-code-") as tmp:
                runner_path = Path(tmp) / "runner.py"
                runner_path.write_text(_runner_source(payload), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, "-I", "-S", str(runner_path)],
                    cwd=tmp,
                    env={
                        "LANG": "C.UTF-8",
                        "PATH": os.defpath,
                        "PYTHONHASHSEED": "0",
                    },
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                    preexec_fn=_set_resource_limits if os.name == "posix" else None,
                )
        except subprocess.TimeoutExpired:
            return _error_report(
                exercise,
                status="error",
                error_type="timeout",
                summary="Execution exceeded the wall-clock limit.",
                test_id="timeout",
            )
        except (OSError, ValueError, TypeError):
            return _error_report(
                exercise,
                status="error",
                error_type="tool_error",
                summary="The restricted runner could not start.",
                test_id="runner",
            )

        result_line = next(
            (
                line[len(_RESULT_MARKER) :]
                for line in reversed(completed.stdout[-64_000:].splitlines())
                if line.startswith(_RESULT_MARKER)
            ),
            None,
        )
        if result_line is None:
            return _error_report(
                exercise,
                status="error",
                error_type="resource_limit",
                summary="The restricted process ended without a valid report.",
                test_id="resource",
            )
        try:
            result = json.loads(result_line)
        except json.JSONDecodeError:
            return _error_report(
                exercise,
                status="error",
                error_type="tool_error",
                summary="The restricted process returned an invalid report.",
                test_id="runner",
            )
        if "runner_error" in result:
            return _error_report(
                exercise,
                status="failed",
                error_type="runtime_error",
                summary=str(result["runner_error"])[:512],
                test_id="entrypoint",
            )
        outcomes = [CodeTestOutcome.model_validate(item) for item in result["outcomes"]]
        passed = sum(item.status == "passed" for item in outcomes)
        runtime_error = any(item.status == "error" for item in outcomes)
        all_passed = passed == len(exercise.tests)
        return CodePracticeReport(
            status="passed" if all_passed else "failed",
            error_type=(
                "none" if all_passed else "runtime_error" if runtime_error else "test_failure"
            ),
            passed_tests=passed,
            total_tests=len(exercise.tests),
            score=round(100 * passed / len(exercise.tests)),
            outcomes=outcomes,
            hints=[],
            safety_notice=_SAFETY_NOTICE,
        )


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


class BoundedCodePracticeAgent:
    """Execute a deterministic, schema-validated and bounded ReAct loop."""

    def __init__(self, registry: CodePracticeToolRegistry) -> None:
        self.registry = registry

    def generate(
        self,
        *,
        topic: str,
        explanation: str,
        tool_call_limit: int,
    ) -> CodePracticeRun:
        return self.run(
            stage="generate",
            actions=[
                {
                    "tool_name": "generate_code_exercise",
                    "arguments": {
                        "topic": topic,
                        "explanation": explanation,
                        "difficulty": "application",
                    },
                }
            ],
            exercise=None,
            tool_call_limit=tool_call_limit,
        )

    def evaluate(
        self,
        *,
        exercise: CodeExercise,
        code: str,
        tool_call_limit: int,
    ) -> CodePracticeRun:
        return self.run(
            stage="evaluate",
            actions=[
                {
                    "tool_name": "run_code_tests",
                    "arguments": {
                        "exercise": exercise.model_dump(mode="json"),
                        "code": code,
                    },
                }
            ],
            exercise=exercise,
            tool_call_limit=tool_call_limit,
        )

    def run(
        self,
        *,
        stage: str,
        actions: list[dict[str, Any]],
        exercise: CodeExercise | None,
        tool_call_limit: int,
    ) -> CodePracticeRun:
        limit = min(max(tool_call_limit, 0), 3)
        if limit == 0:
            return CodePracticeRun(
                tool_calls=0,
                tool_call_limit=0,
                termination_reason="budget_exhausted",
            )
        available = {
            tool.name: tool
            for tool in self.registry.available_tools(
                stage=stage,
                exercise=exercise,
                tool_call_limit=limit,
            )
        }
        trace: list[ToolTraceEntry] = []
        seen: set[str] = set()
        tool_calls = 0
        for action in actions[:3]:
            name = str(action.get("tool_name", ""))
            arguments = action.get("arguments", {})
            canonical = json.dumps(
                {"tool_name": name, "arguments": arguments},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if canonical in seen:
                trace.append(
                    ToolTraceEntry(
                        step=len(trace) + 1,
                        tool_name=name or "unknown",
                        status="rejected",
                        observation="duplicate action rejected",
                    )
                )
                return CodePracticeRun(
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="duplicate_action",
                )
            seen.add(canonical)
            if tool_calls >= limit:
                return CodePracticeRun(
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="budget_exhausted",
                )
            tool = available.get(name)
            if tool is None:
                trace.append(
                    ToolTraceEntry(
                        step=len(trace) + 1,
                        tool_name=name or "unknown",
                        status="rejected",
                        observation="tool is unavailable for this stage",
                    )
                )
                return CodePracticeRun(
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="tool_unavailable",
                )
            tool_calls += 1
            try:
                result = tool.invoke(arguments)
            except Exception:
                trace.append(
                    ToolTraceEntry(
                        step=len(trace) + 1,
                        tool_name=name,
                        status="error",
                        observation="tool input or execution failed",
                    )
                )
                return CodePracticeRun(
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="tool_error",
                )
            if stage == "generate" and result is not None:
                generated = CodeExercise.model_validate(result)
                trace.append(
                    ToolTraceEntry(
                        step=len(trace) + 1,
                        tool_name=name,
                        status="completed",
                        observation=f"exercise generated: {generated.entrypoint}",
                    )
                )
                return CodePracticeRun(
                    exercise=generated,
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="completed",
                )
            if stage == "evaluate" and result is not None:
                report = CodePracticeReport.model_validate(result)
                trace.append(
                    ToolTraceEntry(
                        step=len(trace) + 1,
                        tool_name=name,
                        status="completed",
                        observation=(
                            f"{report.passed_tests}/{report.total_tests} tests passed"
                        ),
                    )
                )
                return CodePracticeRun(
                    report=report,
                    trace=trace,
                    tool_calls=tool_calls,
                    tool_call_limit=limit,
                    termination_reason="completed",
                )
            trace.append(
                ToolTraceEntry(
                    step=len(trace) + 1,
                    tool_name=name,
                    status="completed",
                    observation="tool returned no applicable result",
                )
            )
        return CodePracticeRun(
            trace=trace,
            tool_calls=tool_calls,
            tool_call_limit=limit,
            termination_reason="not_applicable",
        )
