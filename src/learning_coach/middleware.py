from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
    dynamic_prompt,
    wrap_model_call,
)
from langchain.tools import BaseTool, ToolRuntime, tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from learning_coach.context import (
    LearningRuntimeContext,
    TeachingContext,
    build_teaching_context,
)
from learning_coach.hybrid_rag import HybridRetrievalResult, HybridStudyRetriever
from learning_coach.knowledge_graph import GraphStudyRetriever
from learning_coach.retrieval import retrieve_study_sources_with_report
from learning_coach.schemas import (
    ContextReport,
    GraphRAGReport,
    GroundedTeaching,
    RetrievalReport,
    StudySource,
)
from learning_coach.security import hardened_study_context


@dataclass(frozen=True)
class TeachingAgentRuntime:
    """Context visible to teaching middleware and read-only tools."""

    learning: LearningRuntimeContext
    teaching: TeachingContext
    task: dict[str, Any]
    retriever: HybridStudyRetriever | GraphStudyRetriever = field(
        default_factory=GraphStudyRetriever
    )
    retrieval_results: dict[str, HybridRetrievalResult] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )


@tool
def search_study_material(
    query: str,
    runtime: ToolRuntime[TeachingAgentRuntime],
) -> str:
    """Search the current session's pasted study material for relevant evidence."""

    retrieval = search_runtime_material_result(runtime.context, query)
    runtime.context.retrieval_results[query] = retrieval
    if not retrieval.sources:
        return "没有找到相关资料片段。"
    source_context = "\n\n".join(
        (
            f"[{source.source_id}"
            f"{f' | {source.source_name}' if source.source_name else ''}"
            f"{f' · {source.location}' if source.location else ''}] "
            f"{source.text}"
        )
        for source in retrieval.sources
    )
    graph_report = retrieval.graph_report
    if graph_report is None or not graph_report.prerequisites:
        return hardened_study_context(source_context)
    reasons = "\n".join(
        f"- {item.reason}" for item in graph_report.prerequisites
    )
    return hardened_study_context(
        f"{source_context}\n\n前置知识建议：\n{reasons}"
    )


@tool
def inspect_learning_progress(
    runtime: ToolRuntime[TeachingAgentRuntime],
) -> str:
    """Inspect current mastery, recent errors, learning goal and progress summary."""

    return runtime.context.teaching.context_summary


_TOOLS: dict[str, BaseTool] = {
    search_study_material.name: search_study_material,
    inspect_learning_progress.name: inspect_learning_progress,
}


def select_teaching_tools(runtime: TeachingAgentRuntime) -> list[BaseTool]:
    """Expose only tools useful to the current learning state and budget."""

    return [
        _TOOLS[name]
        for name in runtime.teaching.available_tools
        if name in _TOOLS
    ]


def choose_teaching_model(
    runtime: TeachingAgentRuntime,
    primary_model: Any,
    advanced_model: Any | None,
) -> Any:
    """Prefer an optional stronger teaching model for struggling learners."""

    if (
        runtime.teaching.prefer_advanced_model
        and advanced_model is not None
        and _supports_agent_tools(advanced_model)
    ):
        return advanced_model
    return primary_model


def teaching_system_prompt(runtime: TeachingAgentRuntime) -> str:
    """Build a stable system prompt from runtime intent and progress state."""

    context = runtime.teaching
    errors = "；".join(context.recent_errors) or "暂无已确认错误"
    tools = "、".join(context.available_tools) or "无工具；直接完成讲解"
    points = "；".join(context.topic_points) or "未拆解要点；按主题整体讲解"
    mastered = "；".join(context.mastered_points) or "暂无"
    coverage_budget = 400 * max(1, len(context.topic_points))
    return f"""你是技术学习教练。讲解必须覆盖主题要点清单中的每一个要点；已判定掌握的要点简要巩固，未掌握的要点重点讲解并使用具体代码场景。
学习目标：{context.learning_goal}
主题要点：{points}
已掌握要点：{mastered}
当前掌握度：{context.mastery_level}/100，层级：{context.mastery_band}
最近错误：{errors}
可用工具：{tools}
运行预算：最多 {context.model_call_limit} 次模型调用，最多 {context.tool_call_limit} 次工具调用。
仅在确有必要时调用工具；不得重复检索相同问题。最终讲解总长度不超过 {coverage_budget} 字（按要点数量自适应），不要只重复定义，也不要声称使用了未调用的工具。"""


def _runtime(request: ModelRequest[Any]) -> TeachingAgentRuntime:
    runtime = getattr(request.runtime, "context", None)
    if not isinstance(runtime, TeachingAgentRuntime):
        raise RuntimeError("讲解 Agent 缺少有效的 TeachingAgentRuntime。")
    return runtime


@dynamic_prompt
def LearningCoachDynamicPrompt(request: ModelRequest[Any]) -> str:
    return teaching_system_prompt(_runtime(request))


def _context_router(
    *,
    primary_model: Any,
    advanced_model: Any | None,
) -> AgentMiddleware[Any, TeachingAgentRuntime]:
    @wrap_model_call(name="LearningCoachContextRouter")
    def route(
        request: ModelRequest[TeachingAgentRuntime],
        handler: Callable[
            [ModelRequest[TeachingAgentRuntime]], ModelResponse[Any]
        ],
    ) -> ModelResponse[Any]:
        runtime = _runtime(request)
        routed_request = request.override(
            model=choose_teaching_model(
                runtime, primary_model, advanced_model
            ),
            tools=select_teaching_tools(runtime),
        )
        return handler(routed_request)

    return route


def build_teaching_middleware(
    runtime: TeachingAgentRuntime,
    *,
    primary_model: Any,
    advanced_model: Any | None = None,
    fallback_model: Any | None = None,
) -> list[AgentMiddleware[Any, TeachingAgentRuntime]]:
    """Compose dynamic context controls with hard per-run budgets."""

    stack: list[AgentMiddleware[Any, TeachingAgentRuntime]] = [
        LearningCoachDynamicPrompt,
        _context_router(
            primary_model=primary_model,
            advanced_model=advanced_model,
        ),
    ]
    if fallback_model is not None:
        stack.append(ModelFallbackMiddleware(fallback_model))
    stack.append(
        ModelCallLimitMiddleware(
            run_limit=runtime.learning.model_call_limit,
            exit_behavior="error",
        )
    )
    if runtime.learning.tool_call_limit > 0:
        stack.append(
            ToolCallLimitMiddleware(
                run_limit=runtime.learning.tool_call_limit,
                exit_behavior="error",
            )
        )
    return stack


def search_runtime_material(
    runtime: TeachingAgentRuntime, query: str
) -> list[dict[str, Any]]:
    """Execute the read-only material search using runtime-scoped input."""

    return [
        {
            "source_id": source.source_id,
            "text": source.text,
            "score": source.score,
            "source_name": source.source_name,
            "source_uri": source.source_uri,
            "source_type": source.source_type,
            "location": source.location,
            "chunk_hash": source.chunk_hash,
        }
        for source in search_runtime_material_result(runtime, query).sources
    ]


def search_runtime_material_result(
    runtime: TeachingAgentRuntime,
    query: str,
) -> HybridRetrievalResult:
    """Return sources and the bounded trace for one Agent tool query."""

    return retrieve_study_sources_with_report(
        {
            "query": query,
            **runtime.task,
        },
        retriever=runtime.retriever,
    )


def _supports_agent_tools(model: Any) -> bool:
    profile = getattr(model, "profile", None)
    return (
        isinstance(model, BaseChatModel)
        and isinstance(profile, dict)
        and profile.get("tool_calling") is True
    )


def _message_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return message.text


class ContextEngineeredTeaching:
    """Run a bounded middleware Agent or a capability-aware LCEL fallback."""

    def __init__(
        self,
        *,
        primary_model: Any,
        fallback_runnable: Runnable[dict[str, Any], GroundedTeaching],
        advanced_model: Any | None = None,
        agent_fallback_model: Any | None = None,
        retriever: HybridStudyRetriever | GraphStudyRetriever | None = None,
    ) -> None:
        self.primary_model = primary_model
        self.advanced_model = advanced_model
        self.agent_fallback_model = agent_fallback_model
        self.fallback_runnable = fallback_runnable
        self.retriever = retriever or GraphStudyRetriever()

    def invoke(
        self,
        task: dict[str, Any],
        runtime: LearningRuntimeContext,
    ) -> GroundedTeaching:
        agent_runtime, selected_model, selected_tier = self._prepare(task, runtime)
        if not _supports_agent_tools(selected_model):
            return self._invoke_lcel(task, agent_runtime, selected_tier)

        agent = self._build_agent(agent_runtime)
        result = agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": self._user_prompt(
                            task, agent_runtime.teaching
                        ),
                    }
                ]
            },
            context=agent_runtime,
        )
        text, sources, report, retrieval_report, graph_report = self._agent_result(
            result, agent_runtime, selected_tier
        )
        return GroundedTeaching(
            text=text,
            sources=sources,
            context_report=report,
            retrieval_report=retrieval_report,
            graph_report=graph_report,
        )

    def stream(
        self,
        task: dict[str, Any],
        runtime: LearningRuntimeContext,
    ) -> Iterator[GroundedTeaching]:
        """Stream model text while retaining bounded context metadata."""

        agent_runtime, selected_model, selected_tier = self._prepare(task, runtime)
        if not _supports_agent_tools(selected_model):
            yield from self._stream_lcel(task, agent_runtime, selected_tier)
            return

        agent = self._build_agent(agent_runtime)
        final_state: dict[str, Any] = {}
        emitted_text = False
        for event in agent.stream(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": self._user_prompt(
                            task, agent_runtime.teaching
                        ),
                    }
                ]
            },
            context=agent_runtime,
            stream_mode=["messages", "values"],
            version="v2",
        ):
            event_type = event.get("type")
            data = event.get("data")
            if event_type == "values" and isinstance(data, dict):
                final_state = data
                continue
            if event_type != "messages" or not isinstance(data, tuple):
                continue
            message = data[0]
            if not isinstance(message, AIMessage) or message.tool_calls:
                continue
            text = _message_text(message)
            if text:
                emitted_text = True
                yield GroundedTeaching(text=text)

        text, sources, report, retrieval_report, graph_report = self._agent_result(
            final_state, agent_runtime, selected_tier
        )
        if not emitted_text:
            yield GroundedTeaching(text=text)
        yield GroundedTeaching(
            text="",
            sources=sources,
            context_report=report,
            retrieval_report=retrieval_report,
            graph_report=graph_report,
        )

    def _agent_result(
        self,
        result: dict[str, Any],
        agent_runtime: TeachingAgentRuntime,
        selected_tier: str,
    ) -> tuple[
        str,
        list[StudySource],
        ContextReport,
        RetrievalReport | None,
        GraphRAGReport | None,
    ]:
        messages = list(result.get("messages", []))
        ai_messages = [
            message for message in messages if isinstance(message, AIMessage)
        ]
        final_messages = [
            message for message in ai_messages if not message.tool_calls
        ]
        if not final_messages:
            raise RuntimeError("讲解 Agent 没有返回最终讲解。")
        used_tools = [
            call["name"]
            for message in ai_messages
            for call in message.tool_calls
        ]
        sources: list[StudySource] = []
        retrieval_report: RetrievalReport | None = None
        graph_report: GraphRAGReport | None = None
        for message in ai_messages:
            for call in message.tool_calls:
                if call["name"] != search_study_material.name:
                    continue
                query = str(call.get("args", {}).get("query", ""))
                retrieval = agent_runtime.retrieval_results.get(query)
                if retrieval is None:
                    continue
                retrieval_report = retrieval.report
                graph_report = retrieval.graph_report
                sources = list(retrieval.sources)
        return (
            _message_text(final_messages[-1]),
            sources,
            ContextReport(
                mode="agent",
                model_tier=selected_tier,
                available_tools=[
                    tool.name for tool in select_teaching_tools(agent_runtime)
                ],
                used_tools=list(dict.fromkeys(used_tools)),
                model_call_limit=agent_runtime.learning.model_call_limit,
                tool_call_limit=agent_runtime.learning.tool_call_limit,
                model_calls=len(ai_messages),
                tool_calls=len(used_tools),
                summary_applied=bool(agent_runtime.teaching.context_summary),
            ),
            retrieval_report,
            graph_report,
        )

    def _stream_lcel(
        self,
        task: dict[str, Any],
        agent_runtime: TeachingAgentRuntime,
        model_tier: str,
    ) -> Iterator[GroundedTeaching]:
        values = self._lcel_values(task, agent_runtime)
        report_emitted = False
        for chunk in self.fallback_runnable.stream(values):
            grounded = (
                chunk
                if isinstance(chunk, GroundedTeaching)
                else GroundedTeaching.model_validate(chunk)
            )
            report = None
            if not report_emitted:
                report = self._lcel_report(agent_runtime, model_tier)
                report_emitted = True
            yield grounded.model_copy(update={"context_report": report})

    def _prepare(
        self,
        task: dict[str, Any],
        runtime: LearningRuntimeContext,
    ) -> tuple[TeachingAgentRuntime, Any, str]:
        teaching = build_teaching_context(task, runtime)
        agent_runtime = TeachingAgentRuntime(
            learning=runtime,
            teaching=teaching,
            task=dict(task),
            retriever=self.retriever,
        )
        advanced_model = self._compatible_advanced_model()
        selected_model = choose_teaching_model(
            agent_runtime, self.primary_model, advanced_model
        )
        selected_tier = (
            "advanced"
            if advanced_model is not None and selected_model is advanced_model
            else "primary"
        )
        return agent_runtime, selected_model, selected_tier

    def _build_agent(self, runtime: TeachingAgentRuntime) -> Any:
        middleware = build_teaching_middleware(
            runtime,
            primary_model=self.primary_model,
            advanced_model=self._compatible_advanced_model(),
            fallback_model=self.agent_fallback_model,
        )
        return create_agent(
            self.primary_model,
            tools=list(_TOOLS.values()),
            middleware=middleware,
            context_schema=TeachingAgentRuntime,
            name="learning_coach_teaching_agent",
        )

    def _compatible_advanced_model(self) -> Any | None:
        if _supports_agent_tools(self.advanced_model):
            return self.advanced_model
        return None

    def _invoke_lcel(
        self,
        task: dict[str, Any],
        agent_runtime: TeachingAgentRuntime,
        model_tier: str,
    ) -> GroundedTeaching:
        values = self._lcel_values(task, agent_runtime)
        result = self.fallback_runnable.invoke(values)
        grounded = (
            result
            if isinstance(result, GroundedTeaching)
            else GroundedTeaching.model_validate(result)
        )
        return grounded.model_copy(
            update={
                "context_report": self._lcel_report(
                    agent_runtime, model_tier
                )
            }
        )

    @staticmethod
    def _lcel_values(
        task: dict[str, Any], agent_runtime: TeachingAgentRuntime
    ) -> dict[str, Any]:
        values = dict(task)
        values.update(
            learning_goal=agent_runtime.teaching.learning_goal,
            mastery_level=agent_runtime.teaching.mastery_level,
            recent_errors="；".join(agent_runtime.teaching.recent_errors) or "暂无",
            context_summary=agent_runtime.teaching.context_summary,
        )
        return values

    @staticmethod
    def _lcel_report(
        agent_runtime: TeachingAgentRuntime, model_tier: str
    ) -> ContextReport:
        return ContextReport(
            mode="lcel",
            model_tier=model_tier,
            available_tools=[],
            used_tools=[],
            model_call_limit=agent_runtime.learning.model_call_limit,
            tool_call_limit=agent_runtime.learning.tool_call_limit,
            model_calls=1,
            tool_calls=0,
            summary_applied=bool(agent_runtime.teaching.context_summary),
        )

    @staticmethod
    def _user_prompt(
        task: dict[str, Any], teaching: TeachingContext
    ) -> str:
        return f"""主题：{task.get('topic', '')}
诊断重点：{task.get('diagnostic_focus', '暂无')}
诊断难度：{task.get('diagnostic_difficulty', '暂无')}
诊断回答：{task.get('diagnostic_answer', '暂无')}
上次反馈：{task.get('feedback', '暂无')}
尚未掌握：{task.get('missing_point', '暂无')}
学习进展摘要：
{teaching.context_summary}
请根据需要读取学习进展或检索资料，然后给出针对性讲解。"""
