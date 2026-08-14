from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


RetrievalQuality = Literal["sufficient", "insufficient", "empty"]


class RetrievalScore(BaseModel):
    """Normalized component scores for one selected Hybrid RAG chunk."""

    model_config = ConfigDict(extra="forbid")

    keyword: float = Field(ge=0, le=1)
    embedding: float = Field(ge=0, le=1)
    fusion: float = Field(ge=0, le=1)
    rerank: float = Field(ge=0, le=1)


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
    score: float = Field(gt=0, le=1, description="确定性词法相关度")
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
