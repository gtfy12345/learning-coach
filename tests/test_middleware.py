from typing import Any

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import PrivateAttr
from langgraph.runtime import Runtime

from learning_coach.context import (
    LearningRuntimeContext,
    build_teaching_context,
)
from learning_coach.middleware import (
    ContextEngineeredTeaching,
    TeachingAgentRuntime,
    build_teaching_middleware,
    choose_teaching_model,
    select_teaching_tools,
    teaching_system_prompt,
)
from learning_coach.schemas import ContextReport, GroundedTeaching, StudySource


def agent_runtime(
    *, mastery: int = 55, material: str = "", errors: list[str] | None = None
) -> TeachingAgentRuntime:
    values: dict[str, Any] = {
        "topic": "LangGraph 条件边",
        "diagnostic_focus": "路由与终止",
        "diagnostic_answer": "根据文字判断。",
        "feedback": "需要读取结构化 State。",
        "mastery_level": mastery,
        "recent_errors": errors or [],
        "study_material": material,
    }
    runtime = LearningRuntimeContext(
        learning_goal="独立实现有界条件路由",
        model_call_limit=4,
        tool_call_limit=2,
    )
    return TeachingAgentRuntime(
        learning=runtime,
        teaching=build_teaching_context(values, runtime),
        task=values,
    )


def test_dynamic_prompt_contains_goal_mastery_errors_and_budget() -> None:
    runtime = agent_runtime(errors=["遗漏 attempts 上限", "没有说明 score 阈值"])

    prompt = teaching_system_prompt(runtime)

    assert "独立实现有界条件路由" in prompt
    assert "55/100" in prompt
    assert "遗漏 attempts 上限" in prompt
    assert "最多 4 次模型调用" in prompt
    assert "最多 2 次工具调用" in prompt
    assert "300 字内" in prompt


def test_tools_are_selected_from_material_progress_and_budget() -> None:
    with_material = agent_runtime(material="条件边读取 State。")
    without_material = agent_runtime()
    no_budget_values = dict(with_material.task)
    no_budget_learning = LearningRuntimeContext(
        learning_goal="独立实现有界条件路由",
        tool_call_limit=0,
    )
    no_budget = TeachingAgentRuntime(
        learning=no_budget_learning,
        teaching=build_teaching_context(no_budget_values, no_budget_learning),
        task=no_budget_values,
    )

    assert [tool.name for tool in select_teaching_tools(with_material)] == [
        "search_study_material",
        "inspect_learning_progress",
    ]
    assert [tool.name for tool in select_teaching_tools(without_material)] == [
        "inspect_learning_progress"
    ]
    assert select_teaching_tools(no_budget) == []


def test_model_selection_uses_optional_advanced_model_only_when_needed() -> None:
    primary = object()
    advanced = object()

    assert choose_teaching_model(agent_runtime(mastery=30), primary, advanced) is advanced
    assert choose_teaching_model(agent_runtime(mastery=85), primary, advanced) is primary
    assert choose_teaching_model(agent_runtime(mastery=30), primary, None) is primary
    repeated_errors = agent_runtime(
        mastery=75, errors=["错误一", "错误二"]
    )
    assert choose_teaching_model(repeated_errors, primary, advanced) is advanced


def test_middleware_stack_includes_dynamic_context_and_hard_budgets() -> None:
    runtime = agent_runtime(material="条件边读取 State。")
    stack = build_teaching_middleware(runtime, primary_model=object())

    names = [middleware.name for middleware in stack]
    assert "LearningCoachDynamicPrompt" in names
    assert "LearningCoachContextRouter" in names
    model_limit = next(
        middleware
        for middleware in stack
        if isinstance(middleware, ModelCallLimitMiddleware)
    )
    tool_limit = next(
        middleware
        for middleware in stack
        if isinstance(middleware, ToolCallLimitMiddleware)
    )
    assert model_limit.run_limit == 4
    assert model_limit.exit_behavior == "error"
    assert tool_limit.run_limit == 2
    assert tool_limit.exit_behavior == "error"


def test_middleware_rewrites_prompt_tools_and_model_request() -> None:
    runtime_context = agent_runtime(
        mastery=30, material="条件边读取 State。"
    )
    primary = object()
    advanced = object()
    stack = build_teaching_middleware(
        runtime_context,
        primary_model=primary,
        advanced_model=advanced,
    )
    request = ModelRequest(
        model=primary,
        messages=[HumanMessage("请讲解")],
        runtime=Runtime(context=runtime_context),
    )
    captured: list[ModelRequest[Any]] = []

    def capture(routed: ModelRequest[Any]) -> ModelResponse[Any]:
        captured.append(routed)
        return ModelResponse(result=[AIMessage("完成")])

    prompt_middleware, router = stack[:2]
    prompt_middleware.wrap_model_call(request, lambda prompted: router.wrap_model_call(prompted, capture))

    assert captured[0].model is advanced
    assert "独立实现有界条件路由" in captured[0].system_prompt
    assert [tool.name for tool in captured[0].tools] == [
        "search_study_material",
        "inspect_learning_progress",
    ]


class ToolCallingTeachingModel(BaseChatModel):
    profile: dict[str, bool] = {
        "tool_calling": True,
        "structured_output": False,
        "image_inputs": False,
    }
    _calls: int = PrivateAttr(default=0)
    _bound_tools: list[str] = PrivateAttr(default_factory=list)
    always_use_tool: bool = False

    @property
    def _llm_type(self) -> str:
        return "fake-context-teaching"

    def bind_tools(self, tools: Any, *, tool_choice: str | None = None, **kwargs: Any) -> Any:
        self._bound_tools = [tool.name for tool in tools]
        return self

    def _generate(self, messages: Any, **kwargs: Any) -> ChatResult:
        self._calls += 1
        if "search_study_material" in self._bound_tools and (
            self._calls == 1 or self.always_use_tool
        ):
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_study_material",
                        "args": {"query": "条件边 State 路由"},
                        "id": f"search-{self._calls}",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content="条件边应读取 State，并显式限制循环次数。")
        return ChatResult(generations=[ChatGeneration(message=message)])


class FailingToolModel(ToolCallingTeachingModel):
    def _generate(self, messages: Any, **kwargs: Any) -> ChatResult:
        raise RuntimeError("primary agent model failed")


def test_context_engineered_agent_executes_tools_and_reports_budgets() -> None:
    model = ToolCallingTeachingModel()
    fallback = RunnableLambda(
        lambda values: GroundedTeaching(text="LCEL fallback", sources=[])
    )
    engine = ContextEngineeredTeaching(
        primary_model=model,
        fallback_runnable=fallback,
    )
    task = {
        "topic": "LangGraph 条件边",
        "diagnostic_focus": "路由与终止",
        "diagnostic_answer": "根据文字决定。",
        "feedback": "需要读取结构化 State。",
        "mastery_level": 55,
        "recent_errors": ["遗漏 attempts 上限"],
        "study_material": "条件边读取结构化 State，并路由到 retry 或 finish。",
    }
    result = engine.invoke(
        task,
        LearningRuntimeContext(
            learning_goal="独立实现有界条件路由",
            model_call_limit=3,
            tool_call_limit=2,
        ),
    )

    assert result.text == "条件边应读取 State，并显式限制循环次数。"
    assert result.sources == [
        StudySource(
            source_id="material-1#chunk-1",
            text=task["study_material"],
            score=result.sources[0].score,
        )
    ]
    assert result.context_report == ContextReport(
        mode="agent",
        model_tier="primary",
        available_tools=[
            "search_study_material",
            "inspect_learning_progress",
        ],
        used_tools=["search_study_material"],
        model_call_limit=3,
        tool_call_limit=2,
        model_calls=2,
        tool_calls=1,
        summary_applied=True,
    )


def test_context_engineered_agent_streams_text_and_finishes_with_report() -> None:
    model = ToolCallingTeachingModel()
    engine = ContextEngineeredTeaching(
        primary_model=model,
        fallback_runnable=RunnableLambda(
            lambda values: GroundedTeaching(text="LCEL fallback")
        ),
    )
    task = {
        "topic": "LangGraph 条件边",
        "mastery_level": 55,
        "study_material": "条件边读取结构化 State。",
    }

    chunks = list(
        engine.stream(
            task,
            LearningRuntimeContext(
                learning_goal="独立实现有界条件路由",
                model_call_limit=3,
                tool_call_limit=2,
            ),
        )
    )

    assert "".join(chunk.text for chunk in chunks) == (
        "条件边应读取 State，并显式限制循环次数。"
    )
    assert chunks[-1].sources[0].source_id == "material-1#chunk-1"
    assert chunks[-1].context_report == ContextReport(
        mode="agent",
        model_tier="primary",
        available_tools=["search_study_material"],
        used_tools=["search_study_material"],
        model_call_limit=3,
        tool_call_limit=2,
        model_calls=2,
        tool_calls=1,
        summary_applied=True,
    )


def test_context_engineered_teaching_falls_back_for_non_tool_models() -> None:
    fallback = RunnableLambda(
        lambda values: GroundedTeaching(
            text=f"LCEL：{values['learning_goal']} / {values['context_summary']}",
            sources=[],
        )
    )
    engine = ContextEngineeredTeaching(
        primary_model=object(),
        fallback_runnable=fallback,
    )

    result = engine.invoke(
        {"topic": "LCEL", "mastery_level": 80},
        LearningRuntimeContext(learning_goal="掌握 Runnable 组合"),
    )

    assert result.text.startswith("LCEL：掌握 Runnable 组合")
    assert result.context_report.mode == "lcel"
    assert result.context_report.model_calls == 1
    assert result.context_report.tool_calls == 0
    assert result.context_report.used_tools == []


def test_context_engineered_agent_stops_when_tool_budget_is_exceeded() -> None:
    model = ToolCallingTeachingModel(always_use_tool=True)
    engine = ContextEngineeredTeaching(
        primary_model=model,
        fallback_runnable=RunnableLambda(
            lambda values: GroundedTeaching(text="fallback", sources=[])
        ),
    )
    task = {
        "topic": "LangGraph",
        "diagnostic_answer": "错误",
        "study_material": "LangGraph State 条件边。",
    }

    with pytest.raises(Exception, match="[Tt]ool.*limit"):
        engine.invoke(
            task,
            LearningRuntimeContext(
                learning_goal="掌握条件边",
                model_call_limit=4,
                tool_call_limit=1,
            ),
        )


def test_context_engineered_agent_uses_existing_model_fallback() -> None:
    fallback_model = ToolCallingTeachingModel()
    engine = ContextEngineeredTeaching(
        primary_model=FailingToolModel(),
        agent_fallback_model=fallback_model,
        fallback_runnable=RunnableLambda(
            lambda values: GroundedTeaching(text="LCEL fallback", sources=[])
        ),
    )

    result = engine.invoke(
        {"topic": "LangGraph", "diagnostic_answer": "错误"},
        LearningRuntimeContext(
            learning_goal="掌握条件边",
            model_call_limit=3,
            tool_call_limit=1,
        ),
    )

    assert result.text == "条件边应读取 State，并显式限制循环次数。"
    assert fallback_model._calls == 1
