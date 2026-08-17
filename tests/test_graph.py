from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command
from pydantic import ValidationError

from learning_coach.graph import build_learning_graph
from learning_coach.agents import build_teaching_swarm
from learning_coach.context import LearningRuntimeContext
from learning_coach.nodes import LearningCoachNodes
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.schemas import GroundedTeaching, LearningEvent
from learning_coach.state import MAX_LEARNING_EVENTS, append_learning_events


class FakeStructuredModel:
    def __init__(self, owner: "FakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, messages: Any) -> Diagnostic | Assessment:
        if self.schema is Diagnostic:
            self.owner.diagnostic_messages = (
                list(messages.to_messages())
                if hasattr(messages, "to_messages")
                else list(messages)
            )
            return Diagnostic(
                question="两个并行节点都更新 results 时，State 应怎样保存？",
                focus="Reducer 合并语义",
                difficulty="application",
            )
        assert self.schema is Assessment
        return Assessment(
            score=86,
            feedback="已经能说明覆盖与合并的区别。",
            missing_point="还可以补充 Reducer 的类型约束。",
        )


class FakeChatModel:
    def __init__(self) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.diagnostic_messages: list[Any] = []
        self.structured_methods: list[str] = []
        self.responses = iter(
            [
                "默认更新会覆盖旧值，Reducer 可以定义列表合并规则。",
                "请给出一个需要 operator.add 的 State 字段。",
                "你已经理解合并规则，下一步练习并行分支中的状态设计。",
            ]
        )

    def invoke(self, messages: Any) -> AIMessage:
        return AIMessage(content=next(self.responses))

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        self.structured_methods.append(method)
        return FakeStructuredModel(self, schema)


class ScriptedStructuredModel:
    """Structured fake whose assessment scores are scripted per attempt."""

    def __init__(self, owner: "ScriptedFakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, messages: Any) -> Diagnostic | Assessment:
        if self.schema is Diagnostic:
            return Diagnostic(
                question="Command 的 goto 可以同时指向多个节点吗？",
                focus="并行 fan-out",
                difficulty="application",
            )
        assert self.schema is Assessment
        index = min(self.owner.assessment_calls, len(self.owner.scores) - 1)
        score = self.owner.scores[index]
        self.owner.assessment_calls += 1
        return Assessment(
            score=score,
            feedback=f"第 {self.owner.assessment_calls} 次评价：{score} 分。",
            missing_point=f"缺口-{self.owner.assessment_calls}",
        )


class ScriptedFakeChatModel(FakeChatModel):
    """FakeChatModel with enough streamed responses for two remediation rounds."""

    def __init__(self, scores: list[int]) -> None:
        super().__init__()
        self.scores = scores
        self.assessment_calls = 0
        self.responses = iter(
            [
                "第一次讲解：并行分支需要 Reducer 合并。",
                "第一次练习：说明默认覆盖的风险。",
                "第二次讲解：补救讲解聚焦上一次缺口。",
                "第二次练习：再给一个并行写入的例子。",
                "两次尝试后的小结：说明合并与终止边界。",
            ]
        )

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> ScriptedStructuredModel:
        self.structured_methods.append(method)
        return ScriptedStructuredModel(self, schema)


def test_graph_pauses_for_two_answers_then_finishes() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "test-learning-session"}}

    result = graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0}, config=config
    )
    assert result["__interrupt__"][0].value["kind"] == "diagnostic"

    result = graph.invoke(Command(resume="后执行的节点会覆盖前一个。"), config)
    assert result["__interrupt__"][0].value["kind"] == "quiz"

    result = graph.invoke(Command(resume="Annotated[list, operator.add]"), config)
    assert result["score"] == 86
    assert result["attempts"] == 1
    assert result["diagnostic_focus"] == "Reducer 合并语义"
    assert result["diagnostic_difficulty"] == "application"
    assert "下一步" in result["summary"]


def test_teach_first_starts_with_lesson_then_skips_remediation_when_check_passes() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "teach-first-pass"}}

    started = graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "learning_mode": "teach_first",
            "attempts": 0,
        },
        config=config,
    )

    assert started["initial_lesson"].startswith("默认更新会覆盖旧值")
    assert started["__interrupt__"][0].value["kind"] == "understanding_check"

    checked = graph.invoke(Command(resume="Reducer 会合并并行更新。"), config)

    assert checked["__interrupt__"][0].value["kind"] == "quiz"
    assert checked["understanding_check"]["score"] == 86
    assert checked["attempts"] == 0
    assert "teaching_plan" not in checked


def test_teach_first_routes_failed_check_through_targeted_teaching() -> None:
    model = ScriptedFakeChatModel([55, 86])
    graph = build_learning_graph(model)
    config = {"configurable": {"thread_id": "teach-first-remediation"}}

    started = graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "learning_mode": "teach_first",
            "attempts": 0,
        },
        config=config,
    )
    checked = graph.invoke(Command(resume="并行更新会自动保存。"), config)

    assert started["__interrupt__"][0].value["kind"] == "understanding_check"
    assert checked["__interrupt__"][0].value["kind"] == "quiz"
    assert checked["understanding_check"]["score"] == 55
    assert checked["recent_errors"] == ["缺口-1"]
    assert checked["attempts"] == 0
    assert checked["teaching_plan"]


def test_graph_runtime_context_survives_interrupts_and_updates_progress() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "context-learning-session"}}
    runtime = LearningRuntimeContext(
        learning_goal="能够独立设计 Reducer 合并策略",
        model_call_limit=3,
        tool_call_limit=2,
    )

    result = graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "learning_goal": runtime.learning_goal,
            "mastery_level": 0,
            "recent_errors": [],
            "attempts": 0,
        },
        config=config,
        context=runtime,
    )
    assert result["learning_goal"] == runtime.learning_goal
    assert result["mastery_level"] == 0
    assert result["recent_errors"] == []

    result = graph.invoke(
        Command(resume="后执行的节点会覆盖前一个。"),
        config=config,
        context=runtime,
    )
    assert result["context_report"]["mode"] == "lcel"
    assert runtime.learning_goal in result["context_summary"]

    result = graph.invoke(
        Command(resume="Annotated[list, operator.add]"),
        config=config,
        context=runtime,
    )
    assert result["mastery_level"] == 86
    assert result["recent_errors"] == []
    assert "86/100" in result["context_summary"]


def test_diagnostic_passes_standard_image_content_blocks() -> None:
    model = FakeChatModel()
    nodes = LearningCoachNodes(model)
    image = {"type": "image", "base64": "aW1hZ2U=", "mime_type": "image/png"}

    result = nodes.make_diagnostic(
        {"topic": "状态图", "diagnostic_images": [image]}
    )

    user_message = model.diagnostic_messages[1]
    assert user_message.type == "human"
    assert user_message.content[0]["type"] == "text"
    assert user_message.content[1] == image
    assert result["diagnostic_focus"] == "Reducer 合并语义"


def test_nodes_delegate_state_projection_to_runnables() -> None:
    tasks = LearningCoachRunnables(
        diagnostic=RunnableLambda(
            lambda values: Diagnostic(
                question=f"诊断 {values['topic']}",
                focus="Runnable",
                difficulty="foundation",
            )
        ),
        teaching=RunnableLambda(
            lambda values: GroundedTeaching(
                text=f"讲解 {values['diagnostic_answer']}", sources=[]
            )
        ),
        quiz=RunnableLambda(lambda values: f"练习 {values['explanation']}"),
        assessment=RunnableLambda(
            lambda values: Assessment(
                score=90,
                feedback=f"已评价 {values['quiz_answer']}",
                missing_point="无",
            )
        ),
        summary=RunnableLambda(
            lambda values: f"总结 {values['score']} {values['feedback']}"
        ),
    )
    nodes = LearningCoachNodes(tasks)
    swarm = build_teaching_swarm(tasks)

    diagnostic = nodes.make_diagnostic({"topic": "LCEL"})
    teaching = swarm.invoke(
        {
            "topic": "LCEL",
            **diagnostic,
            "diagnostic_answer": "使用管道组合。",
        }
    )
    quiz = nodes.make_quiz({"topic": "LCEL", **teaching})
    assessment = nodes.assess(
        {
            "topic": "LCEL",
            **quiz,
            "quiz_answer": "Prompt | Model | Parser",
            "attempts": 0,
        }
    )
    summary = nodes.summarize({"topic": "LCEL", **assessment.update})

    assert diagnostic["diagnostic_question"] == "诊断 LCEL"
    assert teaching["explanation"] == "讲解 使用管道组合。"
    assert teaching["teaching_plan"]["uses_research"] is False
    assert quiz["quiz_question"].startswith("练习")
    assert assessment.goto == "summarize"
    assert assessment.update["score"] == 90
    assert assessment.update["attempts"] == 1
    assert summary["summary"].startswith("总结 90")


def test_assessment_tracks_recent_errors_for_remedial_context() -> None:
    tasks = LearningCoachRunnables(
        diagnostic=RunnableLambda(lambda values: None),
        teaching=RunnableLambda(lambda values: None),
        quiz=RunnableLambda(lambda values: "question"),
        assessment=RunnableLambda(
            lambda values: Assessment(
                score=55,
                feedback="应说明循环终止条件。",
                missing_point="遗漏 attempts 上限",
            )
        ),
        summary=RunnableLambda(lambda values: "summary"),
    )
    nodes = LearningCoachNodes(tasks)
    runtime = LearningRuntimeContext(learning_goal="实现有界补救流程")

    result = nodes.assess(
        {
            "topic": "LangGraph",
            "quiz_question": "如何终止？",
            "quiz_answer": "达到分数后停止。",
            "attempts": 0,
            "recent_errors": ["没有说明 score 阈值"],
        },
        runtime=runtime,
    )

    assert result.goto == ["teach", "prepare_practice"]
    assert result.update["mastery_level"] == 55
    assert result.update["recent_errors"] == ["遗漏 attempts 上限"]
    assert "55/100" in result.update["context_summary"]
    assert "遗漏 attempts 上限" in result.update["context_summary"]
    assert "没有说明 score 阈值" in result.update["context_summary"]


def test_graph_streams_task_status_text_and_sources_before_final_state() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "stream-learning-session"}}
    material = "State 是 Reducer 的前置知识。"
    graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "attempts": 0,
            "study_material": material,
        },
        config=config,
    )

    parts = list(
        graph.stream(
            Command(resume="后执行节点会覆盖旧值。"),
            config=config,
            stream_mode=["custom", "values"],
            version="v2",
            subgraphs=True,
        )
    )
    custom = [part["data"] for part in parts if part["type"] == "custom"]
    values = [part["data"] for part in parts if part["type"] == "values"]

    assert any(
        event == {"event": "status", "task": "teaching", "status": "started"}
        for event in custom
    )
    assert any(
        event["event"] == "token"
        and event["task"] == "teaching"
        and "Reducer" in event["text"]
        for event in custom
    )
    source_event = next(event for event in custom if event["event"] == "sources")
    assert source_event["sources"][0]["source_id"].startswith(
        "material-1#chunk-"
    )
    retrieval_event = next(
        event for event in custom if event["event"] == "retrieval"
    )
    assert retrieval_event["report"]["embedding_model_id"] == "local:hash-v1"
    assert len(retrieval_event["report"]["attempts"]) <= 2
    graph_event = next(
        event for event in custom if event["event"] == "knowledge_graph"
    )
    assert graph_event["report"]["graph_used"] is True
    assert graph_event["report"]["prerequisites"][0]["prerequisite_name"] == "State"
    assert values[-1]["explanation"] == "默认更新会覆盖旧值，Reducer 可以定义列表合并规则。"
    assert values[-1]["retrieval_report"] == retrieval_event["report"]
    assert values[-1]["graph_report"] == graph_event["report"]
    assert next(
        part["interrupts"] for part in parts if part.get("interrupts")
    )[0].value["kind"] == "quiz"


def test_graph_runs_code_practice_and_keeps_hidden_tests_server_side() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "code-practice-session"}}

    result = graph.invoke(
        {"topic": "Python 函数", "attempts": 0}, config=config
    )
    result = graph.invoke(
        Command(resume="函数把输入映射为输出。"), config=config
    )

    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "quiz"
    assert payload["code_exercise"]["entrypoint"] == "clamp_score"
    assert "tests" not in payload["code_exercise"]
    assert result["code_exercise"]["tests"]

    result = graph.invoke(
        Command(
            resume=(
                "def clamp_score(score):\n"
                "    return min(100, max(0, score))\n"
            )
        ),
        config=config,
    )

    approval = result["__interrupt__"][0].value
    assert approval["kind"] == "approval"
    assert approval["entrypoint"] == "clamp_score"
    assert approval["total_test_count"] == 4

    result = graph.invoke(Command(resume="approve"), config=config)

    assert result["score"] == 100
    assert result["execution_approved"] is True
    assert result["code_practice_report"]["status"] == "passed"
    assert result["code_practice_report"]["passed_tests"] == 4
    assert result["code_tool_trace"][0]["tool_name"] == "run_code_tests"


def test_graph_rejected_execution_skips_runner_and_keeps_loop() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "rejected-execution-session"}}

    graph.invoke({"topic": "Python 函数", "attempts": 0}, config=config)
    graph.invoke(Command(resume="函数把输入映射为输出。"), config=config)
    result = graph.invoke(
        Command(
            resume=(
                "def clamp_score(score):\n"
                "    return min(100, max(0, score))\n"
            )
        ),
        config=config,
    )
    assert result["__interrupt__"][0].value["kind"] == "approval"

    result = graph.invoke(Command(resume="reject"), config=config)

    assert result["execution_approved"] is False
    assert result["score"] == 0
    report = result["code_practice_report"]
    assert report["status"] == "rejected"
    assert report["passed_tests"] == 0
    assert report["total_tests"] == 4
    approval_events = [
        event
        for event in result["learning_events"]
        if event["node"] == "approve_execution"
    ]
    assert approval_events[-1]["detail"].startswith("已拒绝")
    assert result["attempts"] == 1
    assert result["__interrupt__"][0].value["kind"] == "quiz"


def test_non_code_graph_keeps_model_generated_quiz_and_assessment() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "text-practice-compatible"}}

    graph.invoke({"topic": "概念图关系", "attempts": 0}, config=config)
    result = graph.invoke(Command(resume="前置边有方向。"), config=config)

    assert "operator.add" in result["quiz_question"]
    assert "code_exercise" not in result

    final = graph.invoke(Command(resume="使用有向边。"), config=config)
    assert final["score"] == 86
    assert "code_practice_report" not in final


def test_zero_tool_budget_keeps_python_topic_on_text_quiz_path() -> None:
    tasks = LearningCoachRunnables(
        diagnostic=RunnableLambda(lambda values: None),
        teaching=RunnableLambda(lambda values: None),
        quiz=RunnableLambda(lambda values: "解释函数的输入输出关系。"),
        assessment=RunnableLambda(lambda values: None),
        summary=RunnableLambda(lambda values: "summary"),
    )
    nodes = LearningCoachNodes(tasks)

    result = nodes.make_quiz(
        {"topic": "Python 函数", "explanation": "函数说明"},
        runtime=LearningRuntimeContext(
            learning_goal="理解 Python 函数", tool_call_limit=0
        ),
    )

    assert result == {"quiz_question": "解释函数的输入输出关系。"}


def test_append_learning_events_merges_parallel_updates_and_caps_size() -> None:
    assert append_learning_events(
        [{"node": "teach"}], [{"node": "prepare_practice"}]
    ) == [{"node": "teach"}, {"node": "prepare_practice"}]
    assert append_learning_events([], None) == []
    events = [{"node": "teach", "index": index} for index in range(MAX_LEARNING_EVENTS)]
    merged = append_learning_events(events, [{"node": "assess"}])
    assert len(merged) == MAX_LEARNING_EVENTS
    assert merged[-1] == {"node": "assess"}
    assert merged[0]["index"] == 1


def test_learning_event_schema_only_accepts_known_nodes() -> None:
    event = LearningEvent(node="prepare_practice", detail="练习类型：text")
    assert event.status == "completed"
    with pytest.raises(ValidationError):
        LearningEvent(node="summarize")
    with pytest.raises(ValidationError):
        LearningEvent(node="teach", detail="d", extra="forbidden")


def test_graph_runs_teach_and_prepare_practice_in_parallel() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "parallel-text-session"}}

    graph.invoke({"topic": "LangGraph Reducer", "attempts": 0}, config=config)
    result = graph.invoke(
        Command(resume="后执行节点会覆盖旧值。"), config=config
    )

    assert result["__interrupt__"][0].value["kind"] == "quiz"
    assert result["practice_kind"] == "text"
    event_nodes = {event["node"] for event in result["learning_events"]}
    assert event_nodes == {"teach", "prepare_practice"}
    for event in result["learning_events"]:
        assert event["status"] == "completed"
        assert event["detail"]
    assert "Reducer" in result["explanation"]


def test_graph_parallel_code_preparation_ready_before_quiz() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "parallel-code-session"}}

    graph.invoke({"topic": "Python 函数", "attempts": 0}, config=config)
    result = graph.invoke(
        Command(resume="函数把输入映射为输出。"), config=config
    )

    payload = result["__interrupt__"][0].value
    assert payload["kind"] == "quiz"
    assert result["practice_kind"] == "code"
    assert payload["code_exercise"]["entrypoint"] == "clamp_score"
    assert result["code_exercise"]["tests"]
    assert result["code_tool_trace"][0]["tool_name"] == "generate_code_exercise"
    prepare_event = next(
        event
        for event in result["learning_events"]
        if event["node"] == "prepare_practice"
    )
    assert "code" in prepare_event["detail"]
    assert "clamp_score" in prepare_event["detail"]


def test_graph_finishes_after_two_failed_attempts_with_parallel_retry() -> None:
    model = ScriptedFakeChatModel(scores=[55, 55])
    graph = build_learning_graph(model)
    config = {"configurable": {"thread_id": "bounded-retry-session"}}

    graph.invoke({"topic": "循环终止", "attempts": 0}, config=config)
    result = graph.invoke(Command(resume="达到分数后停止。"), config=config)
    assert result["__interrupt__"][0].value["kind"] == "quiz"
    result = graph.invoke(Command(resume="分数上限约束重试。"), config=config)
    assert result["__interrupt__"][0].value["kind"] == "quiz"
    assert result["attempts"] == 1
    result = graph.invoke(Command(resume="用完次数后进入总结。"), config=config)

    assert "__interrupt__" not in result
    assert result["attempts"] == 2
    assert result["score"] == 55
    assert result["summary"]
    assert model.assessment_calls == 2
    event_details = [
        event["detail"] for event in result["learning_events"]
    ]
    assert sum(
        1 for detail in event_details if detail.startswith("讲解起草完成")
    ) == 2
    assert sum(1 for detail in event_details if detail.startswith("审查")) >= 2
    event_nodes = [event["node"] for event in result["learning_events"]]
    assert event_nodes.count("assess") == 2
    assert event_nodes.count("prepare_practice") == 2
    handoff_pairs = {
        (item["from_agent"], item["to_agent"])
        for item in result["agent_handoffs"]
    }
    assert ("orchestrator", "teach") in handoff_pairs
    assert ("teach", "review") in handoff_pairs
    assert ("review", "quiz") in handoff_pairs
    assert ("practice", "quiz") in handoff_pairs
    assert result["teaching_plan"]["uses_research"] is False
    assert result["teaching_plan"]["review_dimensions"] == [
        "grounding",
        "alignment",
        "clarity",
    ]
    assert len(result["teaching_reviews"]) >= 4
    assert result["recent_errors"] == ["缺口-1", "缺口-2"]
