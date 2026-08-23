from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from learning_coach.memory import (
    list_question_history,
    record_question_history,
)
from learning_coach.nodes import (
    LearningCoachNodes,
    mastered_points_from_assessment,
)
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import (
    Assessment,
    Diagnostic,
    GroundedTeaching,
    PointAssessment,
    TopicPoints,
)


def _runnables(
    topic_points: Any = None,
) -> LearningCoachRunnables:
    return LearningCoachRunnables(
        diagnostic=RunnableLambda(
            lambda values: Diagnostic(
                question="诊断题？", focus="要点", difficulty="application"
            )
        ),
        teaching=RunnableLambda(lambda values: GroundedTeaching(text="讲解")),
        quiz=RunnableLambda(lambda values: "练习题"),
        assessment=RunnableLambda(
            lambda values: Assessment(
                score=90, feedback="不错", missing_point="无"
            )
        ),
        summary=RunnableLambda(lambda values: "小结"),
        topic_points=topic_points,
    )


def test_topic_points_schema_bounds_and_normalization() -> None:
    breakdown = TopicPoints(points=["  零拷贝传入 ", "所有权与生命周期"])
    assert breakdown.points == ["零拷贝传入", "所有权与生命周期"]

    with pytest.raises(ValidationError):
        TopicPoints(points=["要点", "要点"])
    with pytest.raises(ValidationError):
        TopicPoints(points=["  "])
    with pytest.raises(ValidationError):
        TopicPoints(points=[f"要点{index}" for index in range(6)])
    assert TopicPoints(points=["唯一要点"]).points == ["唯一要点"]


def test_assessment_point_results_default_empty() -> None:
    assessment = Assessment(score=80, feedback="可以", missing_point="无")
    assert assessment.point_results == []


def test_break_down_topic_node_splits_and_degrades() -> None:
    state = {"topic": "零拷贝传入与生命周期管理"}

    working = LearningCoachNodes(
        _runnables(
            RunnableLambda(
                lambda values: TopicPoints(
                    points=["零拷贝传入", "生命周期管理"]
                )
            )
        )
    )
    result = working.break_down_topic(state)
    assert result["topic_points"] == ["零拷贝传入", "生命周期管理"]
    assert result["learning_events"][0]["node"] == "break_down_topic"

    failing = LearningCoachNodes(
        _runnables(RunnableLambda(lambda values: (_ for _ in ()).throw(ValueError("模型不可用"))))
    )
    degraded = failing.break_down_topic(state)
    assert degraded["topic_points"] == [state["topic"]]

    unconfigured = LearningCoachNodes(_runnables(None))
    fallback = unconfigured.break_down_topic(state)
    assert fallback["topic_points"] == [state["topic"]]


def test_mastered_points_projection_follows_topic_list() -> None:
    state = {"topic_points": ["零拷贝传入", "生命周期管理", "类型约束"]}
    assessment = Assessment(
        score=75,
        feedback="部分掌握",
        missing_point="生命周期管理",
        point_results=[
            PointAssessment(point="零拷贝传入", mastered=True),
            PointAssessment(point="生命周期管理", mastered=False, gap="引用计数"),
            PointAssessment(point="类型约束", mastered=True),
        ],
    )
    assert mastered_points_from_assessment(state, assessment) == [
        "零拷贝传入",
        "类型约束",
    ]
    assert mastered_points_from_assessment({}, assessment) == []


def test_question_history_records_and_lists_newest_first() -> None:
    store = InMemoryStore()
    record_question_history(
        store,
        "learner-1",
        topic="第一个问题",
        learning_goal="掌握第一个问题",
        source="teach_first",
    )
    record_question_history(
        store,
        "learner-1",
        topic="第二个问题",
        learning_goal="",
        source="diagnose_first",
    )
    record_question_history(store, "learner-2", topic="其他学习者")

    questions = list_question_history(store, "learner-1")
    assert [item["topic"] for item in questions] == [
        "第二个问题",
        "第一个问题",
    ]
    assert questions[0]["source"] == "diagnose_first"
    assert list_question_history(store, "learner-1", limit=1) == [
        questions[0]
    ]
    assert list_question_history(store, "learner-3") == []
    with pytest.raises(ValueError):
        list_question_history(store, "learner-1", limit=0)
