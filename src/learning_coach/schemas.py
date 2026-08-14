from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Diagnostic(BaseModel):
    """A provider-independent diagnostic question and its teaching metadata."""

    question: str = Field(min_length=1, description="一道不泄露答案的诊断题")
    focus: str = Field(min_length=1, description="这道题主要检查的知识点")
    difficulty: Literal["foundation", "application", "advanced"] = Field(
        description="诊断题难度"
    )


class Assessment(BaseModel):
    """A machine-readable evaluation used by the graph router."""

    score: int = Field(ge=0, le=100, description="回答得分，范围为 0 到 100")
    feedback: str = Field(description="具体、可执行的反馈")
    missing_point: str = Field(description="最主要的知识缺口；没有时写明已经掌握")


CodeDifficulty = Literal["foundation", "application", "advanced"]
CodeErrorType = Literal[
    "none",
    "syntax_error",
    "policy_violation",
    "timeout",
    "resource_limit",
    "runtime_error",
    "test_failure",
    "tool_error",
]


class CodeTestCase(BaseModel):
    """One bounded JSON-compatible test owned by a generated exercise."""

    model_config = ConfigDict(extra="forbid")

    test_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    args: list[object] = Field(default_factory=list, max_length=8)
    expected: object
    visible: bool = False


class CodeExercise(BaseModel):
    """A deterministic single-function Python exercise and its tests."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str = Field(min_length=1, max_length=128)
    instructions: str = Field(min_length=1, max_length=1_000)
    entrypoint: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    starter_code: str = Field(min_length=1, max_length=12_000)
    difficulty: CodeDifficulty
    tests: list[CodeTestCase] = Field(min_length=1, max_length=12)


class GenerateCodeExerciseInput(BaseModel):
    """Validated arguments for the exercise-generation tool."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=300)
    explanation: str = Field(default="", max_length=4_000)
    difficulty: CodeDifficulty = "application"


class RunCodeTestsInput(BaseModel):
    """Validated arguments for the restricted code-test tool."""

    model_config = ConfigDict(extra="forbid")

    exercise: CodeExercise
    code: str = Field(min_length=1, max_length=20_000)


class CodeTestOutcome(BaseModel):
    """Safe result projection for one code test."""

    model_config = ConfigDict(extra="forbid")

    test_id: str = Field(min_length=1, max_length=64)
    status: Literal["passed", "failed", "error"]
    visible: bool = False
    summary: str = Field(default="", max_length=512)
    duration_ms: int = Field(default=0, ge=0, le=10_000)


class CodeHint(BaseModel):
    """One progressively more specific hint for a classified code error."""

    model_config = ConfigDict(extra="forbid")

    level: Literal[1, 2, 3]
    error_type: CodeErrorType
    text: str = Field(min_length=1, max_length=600)


class ToolTraceEntry(BaseModel):
    """A safe Action/Observation entry from the bounded ReAct controller."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(ge=1, le=3)
    tool_name: str = Field(min_length=1, max_length=80)
    status: Literal["completed", "rejected", "error"]
    observation: str = Field(min_length=1, max_length=300)


class CodePracticeReport(BaseModel):
    """Deterministic execution, grading and hint report."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "rejected", "error"]
    error_type: CodeErrorType
    passed_tests: int = Field(ge=0, le=12)
    total_tests: int = Field(ge=0, le=12)
    score: int = Field(ge=0, le=100)
    outcomes: list[CodeTestOutcome] = Field(default_factory=list, max_length=12)
    hints: list[CodeHint] = Field(default_factory=list, max_length=3)
    safety_notice: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_test_counts(self) -> "CodePracticeReport":
        if self.passed_tests > self.total_tests:
            raise ValueError("通过测试数不能超过总测试数。")
        return self


class CodePracticeRun(BaseModel):
    """One bounded ReAct result for generation or evaluation."""

    model_config = ConfigDict(extra="forbid")

    exercise: CodeExercise | None = None
    report: CodePracticeReport | None = None
    trace: list[ToolTraceEntry] = Field(default_factory=list, max_length=3)
    tool_calls: int = Field(ge=0, le=3)
    tool_call_limit: int = Field(ge=0, le=3)
    termination_reason: Literal[
        "completed",
        "not_applicable",
        "budget_exhausted",
        "duplicate_action",
        "tool_unavailable",
        "tool_error",
    ]


RetrievalQuality = Literal["sufficient", "insufficient", "empty"]


class RetrievalScore(BaseModel):
    """Normalized component scores for one selected Hybrid RAG chunk."""

    model_config = ConfigDict(extra="forbid")

    keyword: float = Field(ge=0, le=1)
    embedding: float = Field(ge=0, le=1)
    fusion: float = Field(ge=0, le=1)
    rerank: float = Field(ge=0, le=1)
    graph: float | None = Field(default=None, ge=0, le=1)
    graph_fusion: float | None = Field(default=None, ge=0, le=1)


class RetrievalAttempt(BaseModel):
    """Safe metadata for one bounded Hybrid RAG retrieval attempt."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1, le=2)
    query: str = Field(min_length=1, max_length=1_000)
    keyword_candidates: int = Field(ge=0, le=8)
    embedding_candidates: int = Field(ge=0, le=8)
    selected_candidates: int = Field(ge=0, le=3)
    quality: RetrievalQuality
    reason: str = Field(min_length=1, max_length=256)
    embedding_degraded: bool = False
    degradation_reason: str | None = Field(default=None, max_length=256)


class RetrievalReport(BaseModel):
    """Trace of the original query and at most one corrective retry."""

    model_config = ConfigDict(extra="forbid")

    original_query: str = Field(min_length=1, max_length=1_000)
    final_query: str = Field(min_length=1, max_length=1_000)
    rewritten: bool
    quality: RetrievalQuality
    embedding_model_id: str = Field(min_length=1, max_length=256)
    attempts: list[RetrievalAttempt] = Field(min_length=1, max_length=2)


class StudySource(BaseModel):
    """A bounded study-material excerpt used to ground one explanation."""

    source_id: str = Field(min_length=1, description="当前会话内稳定的资料片段 ID")
    text: str = Field(min_length=1, description="命中的资料片段正文")
    score: float = Field(gt=0, le=1, description="最终归一化检索相关度")
    source_name: str | None = Field(default=None, description="安全的来源文件名或网页名")
    source_uri: str | None = Field(default=None, description="文件名或 http/https 来源 URL")
    source_type: str | None = Field(default=None, description="资料 Loader 类型")
    location: str | None = Field(default=None, description="页码、章节、幻灯片或代码行范围")
    chunk_hash: str | None = Field(default=None, description="用于增量索引的 Chunk SHA-256")
    retrieval_score: RetrievalScore | None = Field(
        default=None,
        description="Hybrid RAG 各阶段归一化分数",
    )
    retrieval_attempt: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description="选中该证据的检索尝试编号",
    )


ConceptKind = Literal["concept", "technology", "code", "abbreviation"]
ConceptRelationType = Literal["prerequisite_of", "part_of", "related_to"]
GraphExtractionMode = Literal["deterministic", "model_augmented", "fallback"]


class ConceptNode(BaseModel):
    """One bounded, provenance-aware concept in the runtime graph."""

    model_config = ConfigDict(extra="forbid")

    concept_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=128)
    normalized_name: str = Field(min_length=1, max_length=128)
    kind: ConceptKind
    aliases: list[str] = Field(default_factory=list, max_length=8)
    chunk_ids: list[str] = Field(default_factory=list, max_length=12)


class ConceptRelation(BaseModel):
    """A directed, evidenced edge in the runtime concept graph."""

    model_config = ConfigDict(extra="forbid")

    relation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    from_concept_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    to_concept_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    relation_type: ConceptRelationType
    confidence: float = Field(ge=0, le=1)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def reject_self_loop(self) -> "ConceptRelation":
        if self.from_concept_id == self.to_concept_id:
            raise ValueError("概念关系不能是自环。")
        return self


class PrerequisiteExplanation(BaseModel):
    """Why one prerequisite is relevant, backed by a bounded graph path."""

    model_config = ConfigDict(extra="forbid")

    target_concept_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_name: str = Field(min_length=1, max_length=128)
    prerequisite_concept_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    prerequisite_name: str = Field(min_length=1, max_length=128)
    path_concept_ids: list[str] = Field(min_length=2, max_length=4)
    path_names: list[str] = Field(min_length=2, max_length=4)
    reason: str = Field(min_length=1, max_length=512)
    evidence_chunk_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_locations: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_path_shape(self) -> "PrerequisiteExplanation":
        if len(self.path_concept_ids) != len(self.path_names):
            raise ValueError("前置路径 ID 与名称数量必须一致。")
        if self.path_concept_ids[0] != self.prerequisite_concept_id:
            raise ValueError("前置路径必须从 prerequisite 开始。")
        if self.path_concept_ids[-1] != self.target_concept_id:
            raise ValueError("前置路径必须以 target 结束。")
        return self


class ConceptGraph(BaseModel):
    """Bounded runtime graph derived from the current session's chunks."""

    model_config = ConfigDict(extra="forbid")

    extraction_mode: GraphExtractionMode
    nodes: list[ConceptNode] = Field(default_factory=list, max_length=80)
    relations: list[ConceptRelation] = Field(default_factory=list, max_length=160)


class GraphRAGReport(BaseModel):
    """Safe graph projection and prerequisite trace for one teaching run."""

    model_config = ConfigDict(extra="forbid")

    extraction_mode: GraphExtractionMode
    graph_used: bool
    nodes: list[ConceptNode] = Field(default_factory=list, max_length=80)
    relations: list[ConceptRelation] = Field(default_factory=list, max_length=160)
    seed_concepts: list[str] = Field(default_factory=list, max_length=12)
    expanded_concepts: list[str] = Field(default_factory=list, max_length=24)
    prerequisites: list[PrerequisiteExplanation] = Field(
        default_factory=list, max_length=5
    )
    hybrid_candidates: int = Field(ge=0, le=8)
    graph_candidates: int = Field(ge=0, le=24)
    selected_candidates: int = Field(ge=0, le=3)


class ContextReport(BaseModel):
    """Safe, bounded metadata describing one context-engineered teaching run."""

    mode: Literal["agent", "lcel"]
    model_tier: Literal["primary", "advanced"]
    available_tools: list[str] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    model_call_limit: int = Field(ge=1)
    tool_call_limit: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    summary_applied: bool


class GroundedTeaching(BaseModel):
    """Teaching text together with the in-memory sources that grounded it."""

    text: str
    sources: list[StudySource] = Field(default_factory=list)
    context_report: ContextReport | None = None
    retrieval_report: RetrievalReport | None = None
    graph_report: GraphRAGReport | None = None
