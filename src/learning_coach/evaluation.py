"""Deterministic evaluation and reporting for the finished learning loop.

Everything here is offline: the retrieval evaluation set runs against the
local hybrid retriever with zero model calls, trajectory checks are structural
invariants over a finished session state, and the stage report aggregates
mastery, trajectory, safety and telemetry into one safe projection.
"""

from typing import Any

from learning_coach.retrieval import retrieve_study_sources_with_report
from learning_coach.schemas import (
    ConceptMastery,
    MasteryMap,
    RetrievalCaseResult,
    RetrievalEvalReport,
    RunTelemetry,
    StageReport,
    TrajectoryCheck,
    TrajectoryEvalReport,
)

MAX_EVALUATION_CASES = 32
MAX_CONCEPTS = 8

EVALUATION_CASES: list[dict[str, Any]] = [
    {
        "case_id": "rag-reducer-basics",
        "topic": "LangGraph Reducer",
        "study_material": (
            "State 是 Reducer 的前置知识。并行分支写同一字段时，"
            "用 Annotated 声明合并函数，operator.add 会拼接列表。"
        ),
        "queries": [
            {"query": "LangGraph Reducer 合并并行写入", "expected_terms": ["reducer"]},
            {"query": "Annotated 声明合并函数", "expected_terms": ["annotated"]},
        ],
    },
    {
        "case_id": "rag-hybrid-recall",
        "topic": "Hybrid RAG",
        "study_material": (
            "BM25 负责关键词召回，Dense 通道负责语义相似。两路结果用 RRF "
            "按名次融合，再经过确定性重排选出最终来源。"
        ),
        "queries": [
            {"query": "BM25 关键词召回", "expected_terms": ["bm25"]},
            {"query": "RRF 融合两路结果", "expected_terms": ["rrf"]},
        ],
    },
    {
        "case_id": "rag-bounded-execution",
        "topic": "受限执行",
        "study_material": (
            "受限执行器先做 AST 校验，拒绝 import 与动态执行，"
            "再在临时目录中运行服务端测试并截断输出。"
        ),
        "queries": [
            {"query": "AST 校验拒绝危险调用", "expected_terms": ["ast"]},
            {"query": "临时目录运行测试", "expected_terms": ["临时目录"]},
        ],
    },
    {
        "case_id": "rag-memory-durable",
        "topic": "检查点记忆",
        "study_material": (
            "Checkpoint 保存每个 superstep 的状态；Store 保存跨会话画像。"
            "会话键带 thread_id，重放覆盖同一键因此幂等。"
        ),
        "queries": [
            {"query": "Checkpoint 保存状态", "expected_terms": ["checkpoint"]},
            {"query": "thread_id 幂等键", "expected_terms": ["thread_id"]},
        ],
    },
]


def evaluate_retrieval(
    cases: list[dict[str, Any]] | None = None,
) -> RetrievalEvalReport:
    """Run the offline retrieval evaluation set (hit@3 + MRR)."""

    selected = (
        EVALUATION_CASES if cases is None else cases
    )[:MAX_EVALUATION_CASES]
    results: list[RetrievalCaseResult] = []
    for case in selected:
        for query_case in case["queries"]:
            query = str(query_case["query"])
            expected = [
                term.casefold() for term in query_case["expected_terms"]
            ]
            result = retrieve_study_sources_with_report(
                {"query": query, "study_material": str(case["study_material"])}
            )
            reciprocal_rank = 0.0
            for rank, source in enumerate(result.sources, start=1):
                text = source.text.casefold()
                if any(term in text for term in expected):
                    reciprocal_rank = 1.0 / rank
                    break
            results.append(
                RetrievalCaseResult(
                    case_id=str(case["case_id"])[:50],
                    query=query[:300],
                    hit=reciprocal_rank > 0.0,
                    reciprocal_rank=reciprocal_rank,
                )
            )
    total = len(results) or 1
    return RetrievalEvalReport(
        cases=results,
        hit_rate=sum(1.0 for item in results if item.hit) / total,
        mrr=sum(item.reciprocal_rank for item in results) / total,
    )


def _terms(text: Any) -> set[str]:
    import re

    normalized = str(text or "").casefold()
    latin = set(re.findall(r"[a-z0-9_]{2,}", normalized))
    cjk = set(re.findall(r"[\u4e00-\u9fff]", normalized))
    return latin | cjk


def evaluate_trajectory(state: dict[str, Any]) -> TrajectoryEvalReport:
    """Check structural invariants of one finished session."""

    checks: list[TrajectoryCheck] = []

    attempts = int(state.get("attempts") or 0)
    checks.append(
        TrajectoryCheck(
            name="bounded_attempts",
            passed=1 <= attempts <= 2,
            detail=f"评价次数 {attempts}（上限 2）",
        )
    )

    reviews = list(state.get("teaching_reviews") or [])
    failed_rounds = {
        int(item.get("round", 0))
        for item in reviews
        if not item.get("passed", True)
    }
    plan = state.get("teaching_plan") or {}
    budget = int(plan.get("revision_budget", 0) or 0)
    revisions = max(failed_rounds) + 1 if failed_rounds else 0
    checks.append(
        TrajectoryCheck(
            name="bounded_revision",
            passed=revisions <= max(budget, 0) + 1,
            detail=f"修订轮次 {revisions}（预算 {budget}）",
        )
    )

    handoffs = list(state.get("agent_handoffs") or [])
    pairs = [
        (item.get("from_agent"), item.get("to_agent")) for item in handoffs
    ]
    checks.append(
        TrajectoryCheck(
            name="handoff_structure",
            passed=bool(handoffs) and ("teach", "review") in pairs,
            detail=f"交接 {len(handoffs)} 次",
        )
    )

    details = [str(event.get("detail")) for event in state.get("learning_events") or []]
    checks.append(
        TrajectoryCheck(
            name="unique_events",
            passed=len(details) == len(set(details)),
            detail=f"事件 {len(details)} 条",
        )
    )

    if state.get("code_exercise"):
        checks.append(
            TrajectoryCheck(
                name="execution_decision_recorded",
                passed=state.get("execution_approved") is not None,
                detail=(
                    "已批准" if state.get("execution_approved")
                    else "已拒绝" if state.get("execution_approved") is False
                    else "缺少审批记录"
                ),
            )
        )

    checks.append(
        TrajectoryCheck(
            name="summary_present",
            passed=bool(str(state.get("summary") or "").strip()),
            detail="学习小结已生成" if state.get("summary") else "缺少学习小结",
        )
    )
    return TrajectoryEvalReport(
        checks=checks,
        passed=all(check.passed for check in checks),
    )


def build_mastery_map(state: dict[str, Any]) -> MasteryMap:
    """Project session signals onto a concept-level mastery map."""

    graph_report = state.get("graph_report") or {}
    concept_names: list[str] = []
    for node in graph_report.get("nodes") or []:
        name = str(node.get("name", "")).strip()
        if name and name not in concept_names:
            concept_names.append(name)
    if not concept_names:
        for candidate in (
            state.get("diagnostic_focus"),
            state.get("topic"),
        ):
            name = str(candidate or "").strip()
            if name:
                concept_names.append(name[:50])

    weak_terms = _terms(
        " ".join(
            [
                str(state.get("missing_point") or ""),
                " ".join(str(e) for e in state.get("recent_errors") or []),
            ]
        )
    )
    practiced_terms = _terms(
        " ".join(
            source.get("text", "")
            for source in state.get("explanation_sources") or []
        )
    )

    concepts: list[ConceptMastery] = []
    for name in concept_names[:MAX_CONCEPTS]:
        name_terms = _terms(name)
        if name_terms & weak_terms:
            band = "weak"
            evidence = "出现在最近知识缺口或评价反馈中"
        elif name_terms & practiced_terms:
            band = "practiced"
            evidence = "出现在本轮讲解引用的资料来源中"
        else:
            band = "introduced"
            evidence = "已在本轮会话中引入"
        concepts.append(
            ConceptMastery(name=name[:50], band=band, evidence=evidence)
        )
    if concepts and not any(concept.band == "weak" for concept in concepts):
        for index, concept in enumerate(concepts):
            if concept.band == "introduced":
                concepts[index] = concept.model_copy(
                    update={
                        "band": "weak",
                        "evidence": "尚无通过评价确认的掌握证据",
                    }
                )
                break

    gaps = [
        str(error)[:60]
        for error in (state.get("recent_errors") or [])[:3]
    ] or ([str(state.get("missing_point") or "")[:60]] if state.get("missing_point") else [])
    score = int(state.get("score") or 0)
    next_steps: list[str] = []
    if gaps:
        next_steps.append(f"针对「{gaps[0]}」再做一次迁移练习")
    if score < 80:
        next_steps.append("复习本轮讲解中的资料来源段落")
    if not next_steps:
        next_steps.append("进入下一个相关主题，保持当前节奏")
    return MasteryMap(
        concepts=concepts,
        focus_gaps=[gap for gap in gaps if gap][:3],
        recommended_next=next_steps[:3],
    )


def build_telemetry(state: dict[str, Any]) -> RunTelemetry:
    """Aggregate safe per-session counters."""

    events = list(state.get("learning_events") or [])
    reviews = list(state.get("teaching_reviews") or [])
    retrieval_report = state.get("retrieval_report") or {}
    return RunTelemetry(
        learning_event_count=len(events),
        handoff_count=len(state.get("agent_handoffs") or []),
        review_count=len(reviews),
        review_pass_count=sum(
            1 for item in reviews if item.get("passed", True)
        ),
        attempts=int(state.get("attempts") or 0),
        retrieval_attempts=len(retrieval_report.get("attempts") or []),
        safety_finding_count=len(state.get("safety_findings") or []),
        practice_kind=str(state.get("practice_kind") or "text")[:20],
    )


def build_stage_report(state: dict[str, Any]) -> StageReport:
    """Assemble the final per-session delivery report."""

    mastery = build_mastery_map(state)
    trajectory = evaluate_trajectory(state)
    telemetry = build_telemetry(state)
    score = int(state.get("score") or 0)
    weak = [concept.name for concept in mastery.concepts if concept.band == "weak"]
    summary = (
        f"最终得分 {score}/100，评价 {telemetry.attempts} 次；"
        f"掌握图谱 {len(mastery.concepts)} 个概念"
        f"（薄弱 {len(weak)} 个）；"
        f"轨迹检查 {'全部通过' if trajectory.passed else '存在未通过项'}；"
        f"安全发现 {telemetry.safety_finding_count} 项。"
    )
    return StageReport(
        mastery=mastery,
        trajectory=trajectory,
        telemetry=telemetry,
        safety_finding_count=telemetry.safety_finding_count,
        summary=summary[:400],
    )


def build_stage_report_node(state: dict[str, Any]) -> dict[str, Any]:
    """Graph node: attach the stage report to the finished session."""

    report = build_stage_report(state)
    return {"stage_report": report.model_dump(mode="json")}
