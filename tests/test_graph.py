from typing import Any

from langgraph.types import Command

from learning_coach.graph import build_learning_graph
from learning_coach.schemas import Assessment


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeAssessmentModel:
    def invoke(self, messages: list[tuple[str, str]]) -> Assessment:
        return Assessment(
            score=86,
            feedback="已经能说明覆盖与合并的区别。",
            missing_point="还可以补充 Reducer 的类型约束。",
        )


class FakeChatModel:
    def __init__(self) -> None:
        self.responses = iter(
            [
                "两个并行节点都更新 results 时，State 应怎样保存？",
                "默认更新会覆盖旧值，Reducer 可以定义列表合并规则。",
                "请给出一个需要 operator.add 的 State 字段。",
                "你已经理解合并规则，下一步练习并行分支中的状态设计。",
            ]
        )

    def invoke(self, messages: list[tuple[str, str]]) -> FakeMessage:
        return FakeMessage(next(self.responses))

    def with_structured_output(self, schema: type[Any]) -> FakeAssessmentModel:
        assert schema is Assessment
        return FakeAssessmentModel()


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
    assert "下一步" in result["summary"]
