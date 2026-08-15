from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from learning_coach.graph import build_learning_graph
from learning_coach.context import LearningRuntimeContext
from learning_coach.nodes import LearningCoachNodes
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.schemas import GroundedTeaching


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


def test_graph_runtime_context_survives_interrupts_and_updates_progress() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "context-learning-session"}}
    runtime = LearningRuntimeContext(
        learning_goal="能够独立设计 Reducer 合并策略",
        model_call_limit=3,
        tool_call_limit=2,
    )

    result = graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
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

    diagnostic = nodes.make_diagnostic({"topic": "LCEL"})
    teaching = nodes.teach(
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
    summary = nodes.summarize({"topic": "LCEL", **assessment})

    assert diagnostic["diagnostic_question"] == "诊断 LCEL"
    assert teaching["explanation"] == "讲解 使用管道组合。"
    assert quiz["quiz_question"].startswith("练习")
    assert assessment["score"] == 90
    assert assessment["attempts"] == 1
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

    assert result["mastery_level"] == 55
    assert result["recent_errors"] == [
        "没有说明 score 阈值",
        "遗漏 attempts 上限",
    ]
    assert "55/100" in result["context_summary"]
    assert "遗漏 attempts 上限" in result["context_summary"]


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

    assert result["score"] == 100
    assert result["code_practice_report"]["status"] == "passed"
    assert result["code_practice_report"]["passed_tests"] == 4
    assert result["code_tool_trace"][0]["tool_name"] == "run_code_tests"


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
