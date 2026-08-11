from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.types import Command

from learning_coach.graph import build_learning_graph
from learning_coach.nodes import LearningCoachNodes
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import Assessment, Diagnostic


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
            lambda values: f"讲解 {values['diagnostic_answer']}"
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
