"""Multi-agent teaching orchestration built on LangGraph primitives.

The teaching phase runs as a bounded orchestrator-worker subgraph: the
orchestrator plans research foci and review dimensions from the learner
context (Router), research workers gather evidence per focus (Send fan-out),
the teacher agent drafts the explanation from the merged evidence, and review
workers check the draft per dimension (Send fan-out) with at most one bounded
revision handoff back to the teacher.
"""

import re
from typing import Annotated, Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, Send

from learning_coach.context import (
    LearningRuntimeContext,
    build_context_summary,
    create_learning_runtime_context,
    mastery_band,
)
from learning_coach.hybrid_rag import (
    HybridRetrievalResult,
    HybridStudyRetriever,
)
from learning_coach.knowledge_graph import (
    GraphStudyRetriever,
    create_graph_retriever,
)
from learning_coach.retrieval import retrieve_study_sources_with_report
from learning_coach.runnables import LearningCoachRunnables
from learning_coach.schemas import (
    AgentHandoff,
    GraphRAGReport,
    LearningEvent,
    ResearchEvidence,
    ResearchFocus,
    ResearchFocusSummary,
    RetrievalReport,
    ReviewDimension,
    ReviewFinding,
    StudySource,
    TeachingPlan,
)
from learning_coach.state import (
    append_agent_handoffs,
    append_learning_events,
    append_research_findings,
    append_teaching_reviews,
)

MAX_RESEARCH_FOCI = 3
DEFAULT_REVISION_BUDGET = 1
MIN_DRAFT_CHARS = 12
MAX_DRAFT_CHARS = 4_000
MAX_EVIDENCE_SOURCES = 3

_NO_FOCUS_MARKERS = {"", "暂无", "无", "没有", "已经掌握", "已掌握"}
_CJK_STOPCHARS = set("的了是在和也就都而及与或不为这那有个们中上下要会可以来去过还被把让")

_LATIN_TERM = re.compile(r"[a-z0-9_]{2,}")
_CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")


def _terms(text: str) -> set[str]:
    """Deterministic term set used by the offline review rules."""

    normalized = (text or "").casefold()
    cjk = {
        character
        for character in _CJK_CHAR.findall(normalized)
        if character not in _CJK_STOPCHARS
    }
    return set(_LATIN_TERM.findall(normalized)) | cjk


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit]


def build_teaching_plan(
    state: dict[str, Any], runtime: LearningRuntimeContext
) -> TeachingPlan:
    """Router: decide research foci and review dimensions from learner context."""

    topic = str(state.get("topic", "")).strip()
    feedback = _bounded_text(state.get("feedback"), 200)
    missing_point = _bounded_text(state.get("missing_point"), 200)

    focus_texts: list[str] = []
    for candidate in (
        state.get("diagnostic_focus"),
        *(state.get("recent_errors") or []),
    ):
        normalized = str(candidate or "").strip()
        if normalized and normalized not in _NO_FOCUS_MARKERS:
            if normalized not in focus_texts:
                focus_texts.append(normalized)

    def focus_query(focus_text: str) -> str:
        return _bounded_text(
            " ".join(part for part in (topic, focus_text, feedback, missing_point) if part),
            300,
        )

    uses_research = bool(
        str(state.get("study_material", "")).strip()
        or state.get("study_chunks")
    )
    foci = []
    if uses_research:
        if not focus_texts:
            focus_texts = [topic or "当前主题"]
        foci = [
            ResearchFocus(label=_bounded_text(text, 50), query=focus_query(text))
            for text in focus_texts[:MAX_RESEARCH_FOCI]
        ]

    dimensions: list[ReviewDimension] = ["grounding"]
    if state.get("recent_errors"):
        dimensions.append("alignment")
    if mastery_band(_int_or_zero(state.get("mastery_level"))) == "foundation":
        dimensions.append("clarity")

    return TeachingPlan(
        research_foci=foci,
        review_dimensions=dimensions,
        revision_budget=DEFAULT_REVISION_BUDGET,
        uses_research=uses_research,
    )


def _int_or_zero(value: Any) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def review_teaching_draft(
    draft: str,
    dimension: ReviewDimension,
    *,
    evidence_texts: list[str],
    focus_terms: set[str],
) -> ReviewFinding:
    """Deterministic per-dimension review of one teaching draft."""

    draft_text = draft or ""
    draft_terms = _terms(draft_text)
    if dimension == "grounding":
        if not evidence_texts:
            return ReviewFinding(
                dimension=dimension,
                round=0,
                passed=True,
                detail="无参考资料，跳过证据对齐。",
            )
        overlap = max(
            (len(draft_terms & _terms(text)) for text in evidence_texts),
            default=0,
        )
        return ReviewFinding(
            dimension=dimension,
            round=0,
            passed=overlap >= 1,
            detail=(
                f"草稿与证据共享 {overlap} 个术语。"
                if overlap >= 1
                else "草稿没有引用任何证据术语。"
            ),
        )
    if dimension == "clarity":
        length = len(draft_text.strip())
        passed = MIN_DRAFT_CHARS <= length <= MAX_DRAFT_CHARS
        return ReviewFinding(
            dimension=dimension,
            round=0,
            passed=passed,
            detail=f"草稿长度 {length} 字符。",
        )
    assert dimension == "alignment"
    if not focus_terms:
        return ReviewFinding(
            dimension=dimension,
            round=0,
            passed=True,
            detail="暂无已确认知识缺口，跳过对齐检查。",
        )
    overlap = draft_terms & focus_terms
    return ReviewFinding(
        dimension=dimension,
        round=0,
        passed=bool(overlap),
        detail=(
            f"草稿回应了缺口术语：{sorted(overlap)[:3]}。"
            if overlap
            else "草稿没有回应最近的知识缺口。"
        ),
    )


class TeachingSwarmInput(TypedDict, total=False):
    """Parent state projection consumed by the teaching swarm."""

    topic: str
    learning_goal: str
    mastery_level: int
    recent_errors: list[str]
    context_summary: str
    study_material: str
    study_chunks: list[dict[str, Any]]
    diagnostic_focus: str
    diagnostic_difficulty: str
    diagnostic_answer: str
    feedback: str
    missing_point: str


class TeachingSwarmOutput(TypedDict, total=False):
    """Deltas and results the swarm hands back to the parent graph."""

    explanation: str
    explanation_sources: list[dict[str, Any]]
    context_summary: str
    context_report: dict[str, Any]
    retrieval_report: dict[str, Any]
    graph_report: dict[str, Any]
    teaching_plan: dict[str, Any]
    research_evidence: dict[str, Any]
    teaching_reviews: Annotated[list[dict[str, Any]], append_teaching_reviews]
    agent_handoffs: Annotated[list[dict[str, Any]], append_agent_handoffs]
    learning_events: Annotated[list[dict[str, Any]], append_learning_events]


class TeachingSwarmState(TeachingSwarmInput, total=False):
    """Internal swarm channels; only output-schema keys flow to the parent."""

    teaching_plan: dict[str, Any]
    research_evidence: dict[str, Any]
    prepared_retrieval: HybridRetrievalResult
    research_findings: Annotated[list[dict[str, Any]], append_research_findings]
    teaching_draft: str
    teaching_reviews: Annotated[list[dict[str, Any]], append_teaching_reviews]
    agent_handoffs: Annotated[list[dict[str, Any]], append_agent_handoffs]
    learning_events: Annotated[list[dict[str, Any]], append_learning_events]
    revision_count: int
    explanation: str
    explanation_sources: list[dict[str, Any]]
    context_summary: str
    context_report: dict[str, Any]
    retrieval_report: dict[str, Any]
    graph_report: dict[str, Any]


def _write_event(event: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer(event)


def _write_status(task: str, status: str) -> None:
    _write_event({"event": "status", "task": task, "status": status})


def _write_token(task: str, text: str) -> None:
    if text:
        _write_event({"event": "token", "task": task, "text": text})


def _handoff(
    from_agent: str, to_agent: str, payload: str, reason: str
) -> dict[str, Any]:
    return AgentHandoff(
        from_agent=from_agent,  # type: ignore[arg-type]
        to_agent=to_agent,  # type: ignore[arg-type]
        payload=_bounded_text(payload, 200),
        reason=_bounded_text(reason, 200),
    ).model_dump(mode="json")


def _event(detail: str) -> dict[str, Any]:
    return LearningEvent(node="teach", detail=_bounded_text(detail, 200)).model_dump(
        mode="json"
    )


def resolve_teaching_retriever(
    runnables: LearningCoachRunnables,
) -> HybridStudyRetriever | GraphStudyRetriever:
    engine = getattr(runnables, "teaching_engine", None)
    retriever = getattr(engine, "retriever", None) if engine else None
    if isinstance(retriever, (HybridStudyRetriever, GraphStudyRetriever)):
        return retriever
    return create_graph_retriever()


class TeachingSwarm:
    """Orchestrator-worker nodes for one bounded teaching round."""

    def __init__(
        self,
        runnables: LearningCoachRunnables,
        *,
        retriever: HybridStudyRetriever | GraphStudyRetriever | None = None,
    ) -> None:
        self.runnables = runnables
        self.retriever = retriever or resolve_teaching_retriever(runnables)

    # -- orchestrator + router -------------------------------------------

    def plan(
        self,
        state: TeachingSwarmState,
        runtime: Runtime[LearningRuntimeContext]
        | LearningRuntimeContext
        | None = None,
    ) -> Command:
        learning_runtime = _runtime_context(state, runtime)
        plan = build_teaching_plan(state, learning_runtime)
        _write_status("teaching", "started")
        base_update: dict[str, Any] = {
            "teaching_plan": plan.model_dump(mode="json"),
            "revision_count": 0,
        }
        if plan.uses_research and plan.research_foci:
            base_update["agent_handoffs"] = [
                _handoff(
                    "orchestrator",
                    "research",
                    f"{len(plan.research_foci)} 个焦点",
                    "按薄弱点并行取证",
                )
            ]
            shared = self._research_shared_input(state)
            sends = [
                Send(
                    "research_worker",
                    {**shared, "focus": focus.model_dump(mode="json"), "order": index},
                )
                for index, focus in enumerate(plan.research_foci)
            ]
            return Command(goto=sends, update=base_update)
        base_update["agent_handoffs"] = [
            _handoff(
                "orchestrator", "teach", "跳过研究", "无学习资料，直接讲解"
            )
        ]
        return Command(goto="teach_agent", update=base_update)

    @staticmethod
    def _research_shared_input(
        state: TeachingSwarmState,
    ) -> dict[str, Any]:
        keys = (
            "topic",
            "study_material",
            "study_chunks",
            "diagnostic_focus",
            "feedback",
            "missing_point",
            "recent_errors",
            "learning_goal",
            "mastery_level",
            "context_summary",
        )
        return {key: state[key] for key in keys if key in state}

    # -- research workers (Send fan-out) ---------------------------------

    def research_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        focus = ResearchFocus.model_validate(state["focus"])
        order = int(state.get("order", 0))
        result = retrieve_study_sources_with_report(
            {
                "query": focus.query,
                **{
                    key: state[key]
                    for key in (
                        "topic",
                        "study_material",
                        "study_chunks",
                        "diagnostic_focus",
                        "feedback",
                        "missing_point",
                        "recent_errors",
                        "learning_goal",
                        "mastery_level",
                        "context_summary",
                    )
                    if key in state
                },
            },
            retriever=self.retriever,
        )
        finding = {
            "order": order,
            "label": focus.label,
            "sources": [source.model_dump(mode="json") for source in result.sources],
            "report": result.report.model_dump(mode="json"),
            "graph_report": (
                result.graph_report.model_dump(mode="json")
                if result.graph_report is not None
                else None
            ),
        }
        return {
            "research_findings": [finding],
            "learning_events": [
                _event(
                    f"研究焦点「{focus.label}」命中 {len(result.sources)} 个来源"
                )
            ],
            "agent_handoffs": [
                _handoff(
                    "research",
                    "teach",
                    f"焦点「{focus.label}」来源 {len(result.sources)} 个",
                    "研究证据待汇合",
                )
            ],
        }

    def synthesize_evidence(self, state: TeachingSwarmState) -> dict[str, Any]:
        findings = sorted(
            state.get("research_findings") or [],
            key=lambda item: int(item.get("order", 0)),
        )
        if not findings:
            # Research produced nothing; the teacher falls back to its own
            # retrieval path instead of receiving an empty evidence packet.
            return {
                "research_evidence": ResearchEvidence().model_dump(mode="json"),
                "learning_events": [_event("研究无结果，教师回退自行检索")],
            }
        merged: dict[str, dict[str, Any]] = {}
        for finding in findings:
            for source in finding.get("sources", []):
                source_id = str(source.get("source_id", ""))
                existing = merged.get(source_id)
                if existing is None or float(source.get("score", 0)) > float(
                    existing.get("score", 0)
                ):
                    merged[source_id] = source
        selected = sorted(
            merged.values(), key=lambda item: float(item.get("score", 0)), reverse=True
        )[:MAX_EVIDENCE_SOURCES]
        primary = findings[0]
        prepared = HybridRetrievalResult(
            sources=[StudySource.model_validate(source) for source in selected],
            report=RetrievalReport.model_validate(primary["report"]),
            graph_report=(
                GraphRAGReport.model_validate(primary["graph_report"])
                if primary.get("graph_report") is not None
                else None
            ),
        )
        evidence = ResearchEvidence(
            foci=[
                ResearchFocusSummary(
                    label=_bounded_text(finding.get("label"), 50)
                    or f"焦点 {index + 1}",
                    query=_bounded_text(
                        _query_from_report(finding.get("report")), 300
                    )
                    or "检索查询不可用",
                    source_count=len(finding.get("sources", [])),
                    quality=_bounded_text(
                        _quality_from_report(finding.get("report")), 30
                    ),
                )
                for index, finding in enumerate(findings)
            ],
            selected_source_ids=[str(source.get("source_id")) for source in selected],
            primary_focus=_bounded_text(primary.get("label"), 50),
        )
        return {
            "research_evidence": evidence.model_dump(mode="json"),
            "prepared_retrieval": prepared,
            "learning_events": [_event(f"证据汇合：去重后 {len(selected)} 个来源")],
            "agent_handoffs": [
                _handoff(
                    "research",
                    "teach",
                    f"合并 {len(selected)} 个来源",
                    "移交教学证据",
                )
            ],
        }

    # -- teacher agent ----------------------------------------------------

    def teach_agent(
        self,
        state: TeachingSwarmState,
        runtime: Runtime[LearningRuntimeContext]
        | LearningRuntimeContext
        | None = None,
    ) -> dict[str, Any]:
        learning_runtime = _runtime_context(state, runtime)
        revision_count = int(state.get("revision_count", 0))
        feedback = str(state.get("feedback", "暂无"))
        if revision_count > 0:
            failed = [
                ReviewFinding.model_validate(item)
                for item in state.get("teaching_reviews", [])
                if not item.get("passed", True)
            ]
            hints = "；".join(
                f"{item.dimension}: {item.detail}" for item in failed[-3:]
            )
            feedback = _bounded_text(f"{feedback} 审查意见：{hints}", 2_000)
        task_input: dict[str, Any] = {
            "topic": state["topic"],
            "topic_points": list(state.get("topic_points", [])),
            "mastered_points": list(state.get("mastered_points", [])),
            "diagnostic_focus": state.get("diagnostic_focus", "暂无"),
            "diagnostic_difficulty": state.get("diagnostic_difficulty", "暂无"),
            "diagnostic_answer": state.get("diagnostic_answer", "暂无"),
            "feedback": feedback,
            "missing_point": state.get("missing_point", "暂无"),
            "study_material": state.get("study_material", ""),
            "study_chunks": state.get("study_chunks", []),
            "learning_goal": learning_runtime.learning_goal,
            "mastery_level": state.get("mastery_level", 0),
            "recent_errors": list(state.get("recent_errors", [])),
            "context_summary": state.get("context_summary", ""),
        }
        prepared = state.get("prepared_retrieval")
        if isinstance(prepared, HybridRetrievalResult):
            task_input["prepared_retrieval"] = prepared

        text_parts: list[str] = []
        sources: list[Any] = []
        context_report: Any = None
        retrieval_report: Any = None
        graph_report: Any = None
        for teaching in self.runnables.teach_stream(task_input, learning_runtime):
            if teaching.retrieval_report is not None and retrieval_report is None:
                retrieval_report = teaching.retrieval_report
                _write_event(
                    {
                        "event": "retrieval",
                        "task": "teaching",
                        "report": retrieval_report.model_dump(),
                    }
                )
            if teaching.graph_report is not None and graph_report is None:
                graph_report = teaching.graph_report
                _write_event(
                    {
                        "event": "knowledge_graph",
                        "task": "teaching",
                        "report": graph_report.model_dump(),
                    }
                )
            if teaching.sources and not sources:
                sources = list(teaching.sources)
                _write_event(
                    {
                        "event": "sources",
                        "task": "teaching",
                        "sources": [source.model_dump() for source in sources],
                    }
                )
            if teaching.context_report is not None and context_report is None:
                context_report = teaching.context_report
            if teaching.text:
                text_parts.append(teaching.text)
                _write_token("teaching", teaching.text)
        draft = "".join(text_parts)
        result: dict[str, Any] = {
            "teaching_draft": draft,
            "explanation": draft,
            "explanation_sources": [
                source.model_dump() for source in sources
            ],
            "context_summary": state.get("context_summary")
            or build_context_summary(state, learning_runtime),
            "learning_events": [
                _event(
                    f"讲解起草完成 · 第 {revision_count + 1} 稿 · "
                    f"参考来源 {len(sources)} 个"
                )
            ],
            "agent_handoffs": [
                _handoff(
                    "teach",
                    "review",
                    f"草稿 {len(draft)} 字符",
                    "按维度并行审查",
                )
            ],
        }
        if context_report is not None:
            result["context_report"] = context_report.model_dump()
        if retrieval_report is not None:
            result["retrieval_report"] = retrieval_report.model_dump()
        if graph_report is not None:
            result["graph_report"] = graph_report.model_dump()
        return result

    # -- review workers (Send fan-out) ------------------------------------

    def review_dispatcher(self, state: TeachingSwarmState) -> Command:
        plan = TeachingPlan.model_validate(state["teaching_plan"])
        draft = str(state.get("teaching_draft", ""))
        sources = [
            source.get("text", "")
            for source in _prepared_source_texts(state)
        ]
        focus_terms: set[str] = set()
        for candidate in (state.get("missing_point"), *(state.get("recent_errors") or [])):
            focus_terms |= _terms(str(candidate or ""))
        sends = [
            Send(
                "review_worker",
                {
                    "dimension": dimension,
                    "round": int(state.get("revision_count", 0)),
                    "draft": draft,
                    "evidence_texts": sources,
                    "focus_terms": sorted(focus_terms),
                },
            )
            for dimension in plan.review_dimensions
        ]
        return Command(goto=sends)

    def review_worker(self, state: dict[str, Any]) -> dict[str, Any]:
        dimension: ReviewDimension = state["dimension"]
        finding = review_teaching_draft(
            str(state.get("draft", "")),
            dimension,
            evidence_texts=list(state.get("evidence_texts", [])),
            focus_terms=set(state.get("focus_terms", ())),
        )
        finding = finding.model_copy(update={"round": int(state.get("round", 0))})
        return {
            "teaching_reviews": [finding.model_dump(mode="json")],
            "learning_events": [
                _event(
                    f"审查 {dimension} "
                    f"{'通过' if finding.passed else '未通过'}（第 {finding.round + 1} 轮）"
                )
            ],
        }

    # -- bounded revision router -------------------------------------------

    def revise_or_approve(self, state: TeachingSwarmState) -> Command:
        plan = TeachingPlan.model_validate(state["teaching_plan"])
        revision_count = int(state.get("revision_count", 0))
        findings = [
            ReviewFinding.model_validate(item)
            for item in state.get("teaching_reviews", [])
            if int(item.get("round", 0)) == revision_count
        ]
        failed = [item for item in findings if not item.passed]
        if failed and revision_count < plan.revision_budget:
            failed_names = "、".join(item.dimension for item in failed)
            _write_event(
                {
                    "event": "agent_handoff",
                    "from_agent": "review",
                    "to_agent": "teach",
                    "reason": "审查未通过，交回修订",
                    "failed": [item.dimension for item in failed],
                }
            )
            return Command(
                goto="teach_agent",
                update={
                    "revision_count": revision_count + 1,
                    "agent_handoffs": [
                        _handoff(
                            "review",
                            "teach",
                            f"未通过维度：{failed_names}",
                            "审查意见交回修订",
                        )
                    ],
                },
            )
        accepted = bool(failed)
        _write_status("teaching", "completed")
        reason = "带审查意见接受" if accepted else "审查通过，移交练习"
        return Command(
            goto=END,
            update={
                "explanation": str(state.get("teaching_draft", "")),
                "agent_handoffs": [
                    _handoff(
                        "review",
                        "quiz",
                        f"{len(findings)} 项审查"
                        + (f"，{len(failed)} 项未通过" if accepted else ""),
                        reason,
                    )
                ],
            },
        )


def _runtime_context(
    state: dict[str, Any],
    runtime: Runtime[LearningRuntimeContext]
    | LearningRuntimeContext
    | None,
) -> LearningRuntimeContext:
    if isinstance(runtime, LearningRuntimeContext):
        return runtime
    runtime_context = getattr(runtime, "context", None)
    if isinstance(runtime_context, LearningRuntimeContext):
        return runtime_context
    return create_learning_runtime_context(
        state["topic"], learning_goal=state.get("learning_goal")
    )


def _query_from_report(report: dict[str, Any] | None) -> str:
    if not report:
        return ""
    return str(
        report.get("original_query", "") or report.get("final_query", "")
    )


def _quality_from_report(report: dict[str, Any] | None) -> str:
    if not report:
        return ""
    return str(report.get("quality", ""))


def _prepared_source_texts(state: TeachingSwarmState) -> list[dict[str, Any]]:
    prepared = state.get("prepared_retrieval")
    if isinstance(prepared, HybridRetrievalResult):
        return [
            {"source_id": source.source_id, "text": source.text}
            for source in prepared.sources
        ]
    return []


def build_teaching_swarm(
    runnables: LearningCoachRunnables,
    *,
    retriever: HybridStudyRetriever | GraphStudyRetriever | None = None,
) -> Any:
    """Compile the teaching swarm subgraph used as the parent ``teach`` node."""

    from learning_coach.context import LearningRuntimeContext as _Context

    swarm = TeachingSwarm(runnables, retriever=retriever)
    builder: StateGraph = StateGraph(
        TeachingSwarmState,
        input_schema=TeachingSwarmInput,
        output_schema=TeachingSwarmOutput,
        context_schema=_Context,
    )

    builder.add_node(
        "plan_teaching",
        swarm.plan,
        destinations=("research_worker", "teach_agent"),
    )
    builder.add_node("research_worker", swarm.research_worker)
    builder.add_node("synthesize_evidence", swarm.synthesize_evidence)
    builder.add_node("teach_agent", swarm.teach_agent)
    builder.add_node(
        "review_dispatcher", swarm.review_dispatcher, destinations=("review_worker",)
    )
    builder.add_node("review_worker", swarm.review_worker)
    builder.add_node(
        "revise_or_approve",
        swarm.revise_or_approve,
        destinations=("teach_agent", END),
    )

    builder.add_edge(START, "plan_teaching")
    builder.add_edge("research_worker", "synthesize_evidence")
    builder.add_edge("synthesize_evidence", "teach_agent")
    builder.add_edge("teach_agent", "review_dispatcher")
    builder.add_edge("review_worker", "revise_or_approve")
    builder.add_edge("revise_or_approve", END)

    return builder.compile()
