from typing import Any

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command, RetryPolicy
from pydantic import ValidationError

from learning_coach.agents import (
    TeachingSwarm,
    build_teaching_plan,
    build_teaching_swarm,
    review_teaching_draft,
    resolve_teaching_retriever,
)
from learning_coach.context import LearningRuntimeContext
from learning_coach.graph import build_learning_graph
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import (
    AgentHandoff,
    Assessment,
    Diagnostic,
    GroundedTeaching,
    ResearchFocus,
    TeachingPlan,
)
from learning_coach.state import (
    MAX_AGENT_HANDOFFS,
    MAX_TEACHING_REVIEWS,
    append_agent_handoffs,
    append_teaching_reviews,
)
from learning_coach.resilience import retry_transient_model_errors

RUNTIME = LearningRuntimeContext(learning_goal="掌握多 Agent 编排")


class RateLimitError(Exception):
    pass


def _tasks(teaching_fn: Any) -> LearningCoachRunnables:
    return LearningCoachRunnables(
        diagnostic=RunnableLambda(
            lambda values: Diagnostic(
                question="Router 应该依据什么决定 worker？",
                focus="编排计划",
                difficulty="application",
            )
        ),
        teaching=RunnableLambda(teaching_fn),
        quiz=RunnableLambda(lambda values: "练习：说明 Handoff 的边界。"),
        assessment=RunnableLambda(
            lambda values: Assessment(
                score=90, feedback="回答合理。", missing_point="无"
            )
        ),
        summary=RunnableLambda(lambda values: "总结：编排有界。"),
    )


def test_teaching_plan_schema_rejects_inconsistent_values() -> None:
    with pytest.raises(ValidationError):
        TeachingPlan(
            research_foci=[],
            review_dimensions=["grounding"],
            revision_budget=1,
            uses_research=True,
        )
    with pytest.raises(ValidationError):
        TeachingPlan(
            research_foci=[ResearchFocus(label="焦点", query="查询")],
            review_dimensions=["grounding"],
            revision_budget=1,
            uses_research=False,
        )
    with pytest.raises(ValidationError):
        TeachingPlan(
            research_foci=[],
            review_dimensions=["grounding", "grounding"],
            revision_budget=1,
            uses_research=False,
        )
    with pytest.raises(ValidationError):
        AgentHandoff(from_agent="orchestrator", to_agent="unknown", reason="r")


def test_build_teaching_plan_routes_by_material_and_context() -> None:
    no_material = build_teaching_plan(
        {"topic": "编排", "mastery_level": 90, "diagnostic_focus": "Send"},
        RUNTIME,
    )
    assert no_material.uses_research is False
    assert no_material.research_foci == []
    assert no_material.review_dimensions == ["grounding"]

    with_material = build_teaching_plan(
        {
            "topic": "编排",
            "mastery_level": 70,
            "diagnostic_focus": "Send 动态 fan-out",
            "recent_errors": ["遗漏修订上限", "Send 动态 fan-out"],
            "study_material": "编排资料",
        },
        RUNTIME,
    )
    assert with_material.uses_research is True
    assert [focus.label for focus in with_material.research_foci] == [
        "Send 动态 fan-out",
        "遗漏修订上限",
    ]
    assert with_material.review_dimensions == ["grounding", "alignment"]
    assert with_material.revision_budget == 1

    foundation = build_teaching_plan(
        {
            "topic": "编排",
            "mastery_level": 0,
            "study_material": "资料",
            "diagnostic_focus": "",
        },
        RUNTIME,
    )
    assert foundation.uses_research is True
    assert [focus.label for focus in foundation.research_foci] == ["编排"]
    assert foundation.review_dimensions == ["grounding", "clarity"]


def test_review_rules_cover_three_dimensions() -> None:
    evidence = ["State 是 Reducer 的前置知识。"]
    grounded = review_teaching_draft(
        "默认覆盖有风险，Reducer 定义合并规则，State 是共享载体。",
        "grounding",
        evidence_texts=evidence,
        focus_terms=set(),
    )
    assert grounded.passed is True

    ungrounded = review_teaching_draft(
        "今天讲一个完全无关的话题。",
        "grounding",
        evidence_texts=evidence,
        focus_terms=set(),
    )
    assert ungrounded.passed is False

    no_evidence = review_teaching_draft(
        "任意草稿", "grounding", evidence_texts=[], focus_terms=set()
    )
    assert no_evidence.passed is True
    assert "跳过" in no_evidence.detail

    short = review_teaching_draft(
        "太短。", "clarity", evidence_texts=[], focus_terms=set()
    )
    assert short.passed is False
    normal = review_teaching_draft(
        "这份草稿的长度满足讲解要求。",
        "clarity",
        evidence_texts=[],
        focus_terms=set(),
    )
    assert normal.passed is True

    aligned = review_teaching_draft(
        "本节重点补上 reducer 合并语义。",
        "alignment",
        evidence_texts=[],
        focus_terms={"reducer", "合并"},
    )
    assert aligned.passed is True
    misaligned = review_teaching_draft(
        "本节讲一个别的内容。",
        "alignment",
        evidence_texts=[],
        focus_terms={"reducer"},
    )
    assert misaligned.passed is False
    skipped = review_teaching_draft(
        "草稿", "alignment", evidence_texts=[], focus_terms=set()
    )
    assert skipped.passed is True


def test_review_and_handoff_reducers_keep_bounded_slices() -> None:
    reviews = [{"dimension": "grounding", "round": 0, "passed": True}] * (
        MAX_TEACHING_REVIEWS + 3
    )
    assert len(append_teaching_reviews([], reviews)) == MAX_TEACHING_REVIEWS
    handoffs = [{"from_agent": "teach"}] * (MAX_AGENT_HANDOFFS + 2)
    assert len(append_agent_handoffs([], handoffs)) == MAX_AGENT_HANDOFFS
    assert append_agent_handoffs([{"from_agent": "teach"}], None) == [
        {"from_agent": "teach"}
    ]


def test_swarm_skips_research_without_material() -> None:
    teaching_inputs: list[dict[str, Any]] = []

    def teaching(values: dict[str, Any]) -> GroundedTeaching:
        teaching_inputs.append(values)
        return GroundedTeaching(
            text="无资料时教师直接讲解编排边界与终止条件。", sources=[]
        )

    swarm = build_teaching_swarm(_tasks(teaching))
    result = swarm.invoke(
        {"topic": "多 Agent 编排", "mastery_level": 90}, context=RUNTIME
    )

    assert result["explanation"] == "无资料时教师直接讲解编排边界与终止条件。"
    assert result["teaching_plan"]["uses_research"] is False
    handoffs = result["agent_handoffs"]
    assert handoffs[0]["from_agent"] == "orchestrator"
    assert handoffs[0]["to_agent"] == "teach"
    assert ("teach", "review") in {
        (item["from_agent"], item["to_agent"]) for item in handoffs
    }
    assert all(item["passed"] for item in result["teaching_reviews"])
    assert "research_evidence" not in result
    assert "prepared_retrieval" not in teaching_inputs[0]


def test_swarm_research_send_fanout_merges_evidence() -> None:
    teaching_inputs: list[dict[str, Any]] = []

    def teaching(values: dict[str, Any]) -> GroundedTeaching:
        teaching_inputs.append(values)
        return GroundedTeaching(
            text="Reducer 合并并行写入，Handoff 移交证据，State 是共享载体。",
            sources=[],
        )

    material = "\n\n".join(
        [
            "State 是 Reducer 的前置知识。",
            "Handoff 负责在 Agent 之间移交证据。",
        ]
    )
    swarm = build_teaching_swarm(_tasks(teaching))
    result = swarm.invoke(
        {
            "topic": "多 Agent 编排",
            "mastery_level": 70,
            "diagnostic_focus": "Reducer 合并",
            "recent_errors": ["遗漏 Handoff 边界"],
            "study_material": material,
        },
        context=RUNTIME,
    )

    plan = result["teaching_plan"]
    assert plan["uses_research"] is True
    assert [focus["label"] for focus in plan["research_foci"]] == [
        "Reducer 合并",
        "遗漏 Handoff 边界",
    ]
    research_events = [
        event
        for event in result["learning_events"]
        if event["detail"].startswith("研究焦点")
    ]
    assert len(research_events) == len(plan["research_foci"])
    evidence = result["research_evidence"]
    assert evidence["primary_focus"] == "Reducer 合并"
    assert len(evidence["foci"]) == 2
    assert 1 <= len(evidence["selected_source_ids"]) <= 3
    assert len(teaching_inputs) == 1
    assert "prepared_retrieval" in teaching_inputs[0]
    assert teaching_inputs[0]["prepared_retrieval"].sources
    pairs = {
        (item["from_agent"], item["to_agent"]) for item in result["agent_handoffs"]
    }
    assert ("orchestrator", "research") in pairs
    assert ("research", "teach") in pairs
    assert result["explanation"].startswith("Reducer 合并")


def test_swarm_revises_once_when_clarity_fails() -> None:
    teaching_inputs: list[dict[str, Any]] = []
    drafts = ["太短。", "修订后的讲解说明了清晰度检查的长度边界与修订预算。"]

    def teaching(values: dict[str, Any]) -> GroundedTeaching:
        teaching_inputs.append(values)
        return GroundedTeaching(
            text=drafts[min(len(teaching_inputs) - 1, len(drafts) - 1)],
            sources=[],
        )

    swarm = build_teaching_swarm(_tasks(teaching))
    result = swarm.invoke(
        {"topic": "多 Agent 编排", "mastery_level": 0}, context=RUNTIME
    )

    assert len(teaching_inputs) == 2
    assert "审查意见" in teaching_inputs[1]["feedback"]
    assert result["explanation"] == drafts[1]
    rounds = {(item["round"], item["dimension"]) for item in result["teaching_reviews"]}
    assert (0, "clarity") in rounds
    assert (1, "clarity") in rounds
    revision_handoffs = [
        item
        for item in result["agent_handoffs"]
        if item["from_agent"] == "review" and item["to_agent"] == "teach"
    ]
    assert len(revision_handoffs) == 1
    assert "clarity" in revision_handoffs[0]["payload"]
    final = [
        item
        for item in result["agent_handoffs"]
        if item["from_agent"] == "review" and item["to_agent"] == "quiz"
    ]
    assert final and "通过" in final[0]["reason"]


def test_swarm_accepts_with_findings_when_budget_exhausted() -> None:
    teaching_inputs: list[dict[str, Any]] = []

    def teaching(values: dict[str, Any]) -> GroundedTeaching:
        teaching_inputs.append(values)
        return GroundedTeaching(text="短。", sources=[])

    swarm = build_teaching_swarm(_tasks(teaching))
    result = swarm.invoke(
        {"topic": "多 Agent 编排", "mastery_level": 0}, context=RUNTIME
    )

    assert len(teaching_inputs) == 2
    assert result["explanation"] == "短。"
    final = [
        item
        for item in result["agent_handoffs"]
        if item["to_agent"] == "quiz"
    ]
    assert final and "带审查意见接受" in final[0]["reason"]


def test_swarm_research_failure_degrades_to_teacher_retrieval() -> None:
    teaching_inputs: list[dict[str, Any]] = []

    def teaching(values: dict[str, Any]) -> GroundedTeaching:
        teaching_inputs.append(values)
        return GroundedTeaching(text="教师自行检索后的讲解内容。", sources=[])

    swarm_nodes = TeachingSwarm(_tasks(teaching))
    empty = swarm_nodes.synthesize_evidence({"research_findings": []})
    assert empty["research_evidence"]["foci"] == []
    assert "prepared_retrieval" not in empty


def test_parent_graph_runs_swarm_without_event_duplication() -> None:
    from tests.test_graph import FakeChatModel
    from langgraph.types import Command

    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "swarm-no-duplication"}}

    graph.invoke({"topic": "LangGraph Reducer", "attempts": 0}, config=config)
    result = graph.invoke(
        Command(resume="后执行节点会覆盖旧值。"), config=config
    )

    assert result["__interrupt__"][0].value["kind"] == "quiz"
    event_details = [str(event["detail"]) for event in result["learning_events"]]
    assert len(event_details) == len(set(event_details))
    assert any(detail.startswith("讲解起草完成") for detail in event_details)
    assert result["agent_handoffs"]
    assert result["teaching_plan"]["uses_research"] is False


def test_swarm_node_retries_transient_teaching_failure() -> None:
    from tests.test_graph import FakeChatModel

    class FlakyTeachModel(FakeChatModel):
        def __init__(self) -> None:
            super().__init__()
            self.text_calls = 0
            self.responses = iter(
                [
                    "第一次讲解成功后的内容足够长，满足清晰度边界。",
                    "请说明 Send 与 Command 的区别。",
                    "总结内容。",
                ]
            )

        def invoke(self, messages: Any):
            self.text_calls += 1
            if self.text_calls == 1:
                raise RateLimitError("rate limited")
            from langchain_core.messages import AIMessage

            return AIMessage(content=next(self.responses))

    model = FlakyTeachModel()
    graph = build_learning_graph(
        model,
        retry_policy=RetryPolicy(
            initial_interval=0.0,
            max_attempts=2,
            retry_on=retry_transient_model_errors,
        ),
    )
    config = {"configurable": {"thread_id": "swarm-transient-retry"}}

    graph.invoke({"topic": "多 Agent 编排", "attempts": 0}, config=config)
    result = graph.invoke(
        Command(resume="编排器决定 worker 数量。"), config=config
    )

    assert model.text_calls >= 2
    assert result["__interrupt__"][0].value["kind"] == "quiz"
    assert result["explanation"].startswith("第一次讲解成功")


def test_resolve_teaching_retriever_prefers_engine_retriever() -> None:
    from learning_coach.knowledge_graph import GraphStudyRetriever

    tasks = _tasks(lambda values: GroundedTeaching(text="讲解", sources=[]))
    assert isinstance(resolve_teaching_retriever(tasks), GraphStudyRetriever)
