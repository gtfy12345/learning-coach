import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables.base import Runnable

from learning_coach.model import LearningCoachModels
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import Assessment, Diagnostic, GroundedTeaching


def _messages(value: Any) -> list[Any]:
    if hasattr(value, "to_messages"):
        return list(value.to_messages())
    return list(value)


class FakeStructuredModel:
    def __init__(self, owner: "FakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, value: Any, config: Any | None = None) -> Any:
        if self.schema is Diagnostic:
            self.owner.raw_diagnostic_input = value
        messages = _messages(value)
        if self.schema is Diagnostic:
            self.owner.diagnostic_messages = messages
            return Diagnostic(
                question="为什么并行节点需要 Reducer？",
                focus="Reducer 合并语义",
                difficulty="application",
            )
        self.owner.assessment_messages = messages
        return Assessment(
            score=88,
            feedback="已经区分覆盖与合并。",
            missing_point="还需说明类型约束。",
        )


class FakeChatModel:
    def __init__(self) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.diagnostic_messages: list[Any] = []
        self.raw_diagnostic_input: Any = None
        self.assessment_messages: list[Any] = []
        self.text_messages: list[list[Any]] = []

    def invoke(self, value: Any, config: Any | None = None) -> AIMessage:
        messages = _messages(value)
        self.text_messages.append(messages)
        system = str(messages[0].content)
        if "针对薄弱点讲解" in system:
            return AIMessage(content="Reducer 决定并行更新如何合并。")
        if "新的应用题" in system:
            return AIMessage(content="请设计一个需要列表合并的 State。")
        return AIMessage(content="已掌握合并语义；下一步练习并行分支。")

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        return FakeStructuredModel(self, schema)


def test_task_runnables_compose_prompts_models_and_parsers() -> None:
    model = FakeChatModel()
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(model)
    )
    image = {"type": "image", "base64": "aW1hZ2U=", "mime_type": "image/png"}

    diagnostic = tasks.diagnostic.invoke(
        {"topic": "LangGraph Reducer", "diagnostic_images": [image]}
    )
    teaching = tasks.teaching.invoke(
        {
            "topic": "LangGraph Reducer",
            "diagnostic_focus": diagnostic.focus,
            "diagnostic_difficulty": diagnostic.difficulty,
            "diagnostic_answer": "后写入的值会覆盖旧值。",
            "feedback": "暂无",
            "missing_point": "暂无",
            "study_material": "",
        }
    )
    quiz = tasks.quiz.invoke(
        {"topic": "LangGraph Reducer", "explanation": teaching.text}
    )
    assessment = tasks.assessment.invoke(
        {
            "topic": "LangGraph Reducer",
            "quiz_question": quiz,
            "quiz_answer": "使用 Annotated 和 operator.add。",
        }
    )
    summary = tasks.summary.invoke(
        {
            "topic": "LangGraph Reducer",
            "score": assessment.score,
            "feedback": assessment.feedback,
            "missing_point": assessment.missing_point,
        }
    )

    assert isinstance(diagnostic, Diagnostic)
    assert isinstance(assessment, Assessment)
    assert teaching == GroundedTeaching(
        text="Reducer 决定并行更新如何合并。", sources=[]
    )
    assert quiz == "请设计一个需要列表合并的 State。"
    assert summary.startswith("已掌握")
    diagnostic_content = model.diagnostic_messages[1].content
    assert diagnostic_content[0]["type"] == "text"
    assert diagnostic_content[1] == image
    assert "LangGraph Reducer" in diagnostic_content[0]["text"]
    assert "operator.add" in model.assessment_messages[1].content
    assert isinstance(model.raw_diagnostic_input, list)


class ProgrammableStructuredModel:
    def __init__(self, owner: "ProgrammableModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, value: Any, config: Any | None = None) -> Any:
        self.owner.structured_calls[self.schema] = (
            self.owner.structured_calls.get(self.schema, 0) + 1
        )
        result = self.owner.structured_results[self.schema]
        if isinstance(result, Exception):
            raise result
        return result


class ProgrammableModel:
    def __init__(
        self,
        *,
        text_result: str | Exception,
        diagnostic_result: Any,
        assessment_result: Any,
    ) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.text_result = text_result
        self.text_calls = 0
        self.structured_results = {
            Diagnostic: diagnostic_result,
            Assessment: assessment_result,
        }
        self.structured_calls: dict[type[Any], int] = {}

    def invoke(self, value: Any, config: Any | None = None) -> AIMessage:
        self.text_calls += 1
        if isinstance(self.text_result, Exception):
            raise self.text_result
        return AIMessage(content=self.text_result)

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> ProgrammableStructuredModel:
        return ProgrammableStructuredModel(self, schema)


def test_complete_tasks_fall_back_on_model_and_validation_errors() -> None:
    primary = ProgrammableModel(
        text_result=RuntimeError("primary text failed"),
        diagnostic_result={
            "question": "",
            "focus": "Reducer",
            "difficulty": "application",
        },
        assessment_result=Assessment(
            score=70, feedback="primary", missing_point="primary"
        ),
    )
    fallback = ProgrammableModel(
        text_result="备用模型完成讲解。",
        diagnostic_result=Diagnostic(
            question="备用诊断题",
            focus="Reducer",
            difficulty="foundation",
        ),
        assessment_result=Assessment(
            score=80, feedback="fallback", missing_point="none"
        ),
    )
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(
            primary,
            chat_fallback_model=fallback,
            assessment_fallback_model=fallback,
        )
    )

    explanation = tasks.teaching.invoke(
        {
            "topic": "Reducer",
            "diagnostic_focus": "合并",
            "diagnostic_difficulty": "application",
            "diagnostic_answer": "覆盖",
            "feedback": "暂无",
            "missing_point": "暂无",
            "study_material": "",
        }
    )
    diagnostic = tasks.diagnostic.invoke({"topic": "Reducer"})

    assert explanation.text == "备用模型完成讲解。"
    assert diagnostic.question == "备用诊断题"
    assert primary.text_calls == fallback.text_calls == 1
    assert primary.structured_calls[Diagnostic] == 1
    assert fallback.structured_calls[Diagnostic] == 1


class EchoModel(FakeChatModel):
    def invoke(self, value: Any, config: Any | None = None) -> AIMessage:
        messages = _messages(value)
        return AIMessage(content=str(messages[1].content))


def test_task_batch_preserves_input_order() -> None:
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(EchoModel())
    )

    results = tasks.quiz.batch(
        [
            {"topic": "A", "explanation": "first"},
            {"topic": "B", "explanation": "second"},
        ]
    )

    assert "主题：A" in results[0]
    assert "主题：B" in results[1]


def test_fallback_failure_is_bounded_and_propagates() -> None:
    primary = ProgrammableModel(
        text_result=RuntimeError("primary failed"),
        diagnostic_result=RuntimeError("primary structured failed"),
        assessment_result=RuntimeError("primary assessment failed"),
    )
    fallback = ProgrammableModel(
        text_result=RuntimeError("fallback failed"),
        diagnostic_result=RuntimeError("fallback structured failed"),
        assessment_result=RuntimeError("fallback assessment failed"),
    )
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(
            primary,
            chat_fallback_model=fallback,
            assessment_fallback_model=fallback,
        )
    )

    with pytest.raises(RuntimeError, match="primary failed"):
        tasks.summary.invoke(
            {
                "topic": "Reducer",
                "score": 0,
                "feedback": "none",
                "missing_point": "all",
            }
        )

    assert primary.text_calls == 1
    assert fallback.text_calls == 1


def test_teaching_rag_composes_context_and_returns_sources() -> None:
    model = FakeChatModel()
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(model)
    )

    result = tasks.teaching.invoke(
        {
            "topic": "LangGraph Reducer",
            "diagnostic_focus": "Reducer 合并语义",
            "diagnostic_difficulty": "application",
            "diagnostic_answer": "后写入会覆盖。",
            "feedback": "请补充并行更新。",
            "missing_point": "列表字段的合并规则",
            "study_material": """RunnableSequence 串联多个步骤。

Reducer 决定 LangGraph 并行节点更新同一 State 字段时如何合并。""",
        }
    )

    assert result.text == "Reducer 决定并行更新如何合并。"
    assert result.sources
    assert result.sources[0].source_id.startswith("material-1#chunk-")
    teaching_message = model.text_messages[-1][1].content
    assert "参考资料" in teaching_message
    assert "并行节点" in teaching_message
    assert result.sources[0].text in teaching_message


def test_teaching_runnable_graph_contains_advanced_lcel_composition() -> None:
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(FakeChatModel())
    )

    graph_text = tasks.teaching.get_graph().draw_mermaid()

    assert "Parallel" in graph_text
    assert "Passthrough" in graph_text
    assert "Lambda" in graph_text
    exported = tasks.draw_mermaid("teaching")
    assert "RunnableSequence" in exported
    assert "RunnableAssign" in exported


class StreamingChatModel(Runnable[Any, AIMessage]):
    profile = {
        "structured_output": True,
        "tool_calling": True,
        "image_inputs": True,
    }

    def invoke(
        self, value: Any, config: Any | None = None, **kwargs: Any
    ) -> AIMessage:
        return AIMessage(content="第一段第二段")

    def stream(
        self, value: Any, config: Any | None = None, **kwargs: Any
    ) -> Any:
        yield AIMessageChunk(content="第一段")
        yield AIMessageChunk(content="第二段")

    async def astream(
        self, value: Any, config: Any | None = None, **kwargs: Any
    ) -> Any:
        yield AIMessageChunk(content="第一段")
        yield AIMessageChunk(content="第二段")

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        return FakeStructuredModel(FakeChatModel(), schema)


def test_task_interfaces_support_async_batch_stream_and_graph_export() -> None:
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(StreamingChatModel())
    )
    teaching_input = {
        "topic": "LCEL",
        "diagnostic_focus": "Runnable",
        "diagnostic_difficulty": "foundation",
        "diagnostic_answer": "统一接口",
        "feedback": "暂无",
        "missing_point": "暂无",
        "study_material": "LCEL Runnable 统一 invoke stream batch async 接口。",
    }

    sync_result = tasks.teaching.invoke(teaching_input)
    async_result = asyncio.run(tasks.teaching.ainvoke(teaching_input))
    chunks = list(tasks.teaching.stream(teaching_input))

    async def collect_chunks() -> list[GroundedTeaching]:
        return [chunk async for chunk in tasks.teaching.astream(teaching_input)]

    async_chunks = asyncio.run(collect_chunks())
    batch = tasks.teaching.batch([teaching_input, teaching_input])

    assert sync_result.text == async_result.text == "第一段第二段"
    assert "".join(chunk.text for chunk in chunks) == sync_result.text
    assert "".join(chunk.text for chunk in async_chunks) == sync_result.text
    assert [result.text for result in batch] == ["第一段第二段"] * 2
    assert all(chunks[0].sources)
    assert all(not chunk.sources for chunk in chunks[1:])
    assert tasks.task("quiz") is tasks.quiz
    assert "graph TD" in tasks.draw_mermaid("teaching")
    assert "RunnableAssign" in tasks.draw_mermaid("teaching")
    with pytest.raises(ValueError, match="未知 LCEL 任务"):
        tasks.task("missing")


def test_task_observability_config_uses_safe_stable_metadata() -> None:
    tasks = LearningCoachRunnables.from_models(
        LearningCoachModels.from_models(FakeChatModel())
    )

    for name in ("diagnostic", "teaching", "quiz", "assessment", "summary"):
        config = tasks.task(name).config
        assert config["run_name"] == f"learning_coach_{name}"
        assert config["tags"] == ["learning-coach", f"task:{name}"]
        assert config["metadata"] == {
            "component": "learning-coach",
            "task": name,
        }
        serialized = str(config).lower()
        assert "api_key" not in serialized
        assert "study_material" not in serialized
        assert "answer" not in serialized
