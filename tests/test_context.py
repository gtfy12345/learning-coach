from dataclasses import FrozenInstanceError

import pytest

from learning_coach.context import (
    LearningContextSettings,
    LearningRuntimeContext,
    build_context_summary,
    build_teaching_context,
    create_learning_runtime_context,
    update_recent_errors,
)
from learning_coach.state import LearningState


def test_context_settings_parse_bounded_environment_values() -> None:
    settings = LearningContextSettings.from_environ(
        {
            "CONTEXT_MODEL_CALL_LIMIT": "4",
            "CONTEXT_TOOL_CALL_LIMIT": "3",
        }
    )

    assert settings.model_call_limit == 4
    assert settings.tool_call_limit == 3


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CONTEXT_MODEL_CALL_LIMIT", "0"),
        ("CONTEXT_MODEL_CALL_LIMIT", "11"),
        ("CONTEXT_TOOL_CALL_LIMIT", "-1"),
        ("CONTEXT_TOOL_CALL_LIMIT", "9"),
        ("CONTEXT_TOOL_CALL_LIMIT", "many"),
    ],
)
def test_context_settings_reject_invalid_or_unbounded_budgets(
    name: str, value: str
) -> None:
    with pytest.raises(RuntimeError, match=name):
        LearningContextSettings.from_environ({name: value})


def test_runtime_context_normalizes_goal_and_is_immutable() -> None:
    context = create_learning_runtime_context(
        "  LangGraph 条件边  ",
        learning_goal="  能独立设计可终止的条件路由  ",
        settings=LearningContextSettings(),
    )

    assert context == LearningRuntimeContext(
        learning_goal="能独立设计可终止的条件路由",
        target_mastery=80,
        model_call_limit=3,
        tool_call_limit=2,
    )
    with pytest.raises(FrozenInstanceError):
        context.model_call_limit = 99  # type: ignore[misc]


def test_runtime_context_uses_topic_goal_and_rejects_invalid_values() -> None:
    context = create_learning_runtime_context(
        "LCEL",
        settings=LearningContextSettings(model_call_limit=2, tool_call_limit=1),
    )

    assert context.learning_goal == "掌握主题：LCEL"
    assert context.model_call_limit == 2
    assert context.tool_call_limit == 1

    with pytest.raises(ValueError, match="学习目标不能超过"):
        create_learning_runtime_context("LCEL", learning_goal="x" * 1001)
    with pytest.raises(ValueError, match="目标掌握度"):
        LearningRuntimeContext(
            learning_goal="掌握 LCEL",
            target_mastery=101,
            model_call_limit=3,
            tool_call_limit=2,
        )


def test_learning_state_declares_progress_context_fields() -> None:
    annotations = LearningState.__annotations__

    for field in (
        "learning_goal",
        "mastery_level",
        "recent_errors",
        "context_summary",
        "context_report",
    ):
        assert field in annotations


def test_recent_errors_are_clean_deduplicated_and_bounded() -> None:
    errors = update_recent_errors(
        ["旧错误", "Reducer 类型", "条件边状态"],
        "Reducer 类型",
    )

    assert errors == ["旧错误", "条件边状态", "Reducer 类型"]
    assert update_recent_errors(errors, "新的错误") == [
        "条件边状态",
        "Reducer 类型",
        "新的错误",
    ]
    assert update_recent_errors(errors, "已经掌握") == errors
    assert update_recent_errors(errors, "暂无") == errors


def test_summary_is_deterministic_and_bounded() -> None:
    runtime = LearningRuntimeContext(
        learning_goal="能够独立设计有界的 LangGraph 补救流程",
    )
    values = {
        "topic": "LangGraph 条件路由",
        "mastery_level": 55,
        "recent_errors": ["没有说明 score 阈值", "遗漏 attempts 上限"],
        "diagnostic_focus": "条件路由与终止条件",
        "feedback": "需要同时说明通过条件和次数上限。" * 50,
    }

    summary = build_context_summary(values, runtime)

    assert summary == build_context_summary(values, runtime)
    assert len(summary) <= 600
    assert "独立设计有界" in summary
    assert "55/100" in summary
    assert "遗漏 attempts 上限" in summary


@pytest.mark.parametrize(
    ("mastery", "band", "advanced"),
    [(0, "foundation", True), (59, "foundation", True), (60, "developing", False),
     (79, "developing", False), (80, "mastered", False)],
)
def test_teaching_context_uses_mastery_goal_errors_and_material(
    mastery: int, band: str, advanced: bool
) -> None:
    runtime = LearningRuntimeContext(
        learning_goal="会根据状态设计条件边",
        model_call_limit=4,
        tool_call_limit=2,
    )
    context = build_teaching_context(
        {
            "topic": "LangGraph",
            "mastery_level": mastery,
            "recent_errors": ["未说明终止条件", "没有引用状态字段"],
            "diagnostic_answer": "根据模型文字决定。",
            "feedback": "应读取结构化字段。",
            "study_material": "条件边读取 State 决定下一节点。",
        },
        runtime,
    )

    assert context.learning_goal == runtime.learning_goal
    assert context.mastery_band == band
    assert context.prefer_advanced_model is advanced or len(context.recent_errors) >= 2
    assert context.available_tools == [
        "search_study_material",
        "inspect_learning_progress",
    ]
    assert context.model_call_limit == 4
    assert context.tool_call_limit == 2
    assert "未说明终止条件" in context.context_summary


def test_teaching_context_disables_tools_without_relevant_state_or_budget() -> None:
    context = build_teaching_context(
        {"topic": "LCEL", "mastery_level": 80},
        LearningRuntimeContext(
            learning_goal="掌握 LCEL",
            tool_call_limit=0,
        ),
    )

    assert context.available_tools == []
    assert context.mastery_band == "mastered"
    assert context.prefer_advanced_model is False
