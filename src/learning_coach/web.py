import asyncio
import ipaddress
import json
import os
import threading
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator, model_validator

from learning_coach.auth import run_auth_action
from learning_coach.course import (
    CourseRecord,
    build_course_outline,
    chapter_chunks,
    course_summary,
    list_courses,
    load_course,
    record_chapter_result,
    save_course,
)
from learning_coach.graph import build_learning_graph
from learning_coach.hybrid_rag import RagSettings
from learning_coach.ingestion import (
    COURSE_MATERIAL_LIMITS,
    MAX_SINGLE_MATERIAL_BYTES,
    IngestionReport,
    MaterialIngestionPipeline,
    MaterialInput,
    StudyChunkRecord,
    material_inputs_from_urls,
    validate_material_batch,
)
from learning_coach.loaders import SafeWebFetcher, default_loader_registry
from learning_coach.context import (
    LearningContextSettings,
    LearningRuntimeContext,
    create_learning_runtime_context,
)
from learning_coach.media import MAX_IMAGE_BYTES, image_bytes_content_block
from learning_coach.model import LearningCoachModels, ModelSettings, create_model_suite
from learning_coach.model_config import (
    ApiModelConfigInput,
    PublicRuntimeModelConfig,
    RuntimeModelConfigService,
    RuntimeModelVersion,
    TestedRuntimeModelConfig,
)
from learning_coach.memory import (
    compare_learning_states,
    create_checkpointer,
    create_memory_store,
    fork_session,
    list_session_checkpoints,
)
from learning_coach.retrieval import normalize_study_material
from learning_coach.schemas import (
    AgentHandoff,
    CheckpointMilestone,
    CodeExercise,
    CodeExerciseView,
    CodePracticeReport,
    ContextReport,
    GraphRAGReport,
    LearnerMemoryView,
    LearningEvent,
    ResearchEvidence,
    RetrievalReport,
    ReviewFinding,
    StageReport,
    StudySource,
    TeachingPlan,
    ToolTraceEntry,
)
from learning_coach.security import (
    inspect_content_safety,
    safety_findings_updates,
)
from learning_coach.state import (
    LearningMode,
    learning_mode_for_new_session,
    learning_mode_for_state,
)

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_WEB_RUN_TIMEOUT_SECONDS = 120.0
MAX_COURSE_CORPORA = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def _await_before_deadline(
    awaitable_factory: Callable[[], Any], deadline: float
) -> Any:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise asyncio.TimeoutError
    return await asyncio.wait_for(awaitable_factory(), timeout=remaining)


class SessionNotFoundError(LookupError):
    """Raised when a browser tries to resume an unknown in-memory session."""


def web_run_timeout_seconds(environ: Mapping[str, str]) -> float:
    value = environ.get(
        "WEB_RUN_TIMEOUT_SECONDS", str(DEFAULT_WEB_RUN_TIMEOUT_SECONDS)
    ).strip()
    try:
        timeout = float(value)
    except ValueError as exc:
        raise RuntimeError("WEB_RUN_TIMEOUT_SECONDS 必须是正数。") from exc
    if timeout <= 0:
        raise RuntimeError("WEB_RUN_TIMEOUT_SECONDS 必须是正数。")
    return timeout


def session_run_config(
    session_id: str,
    *,
    has_study_material: bool | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "component": "learning-coach",
        "surface": "web",
        "session_id": session_id,
    }
    if has_study_material is not None:
        metadata["has_study_material"] = has_study_material
    return {
        "configurable": {"thread_id": f"web-{session_id}"},
        "run_name": "learning_coach_session",
        "tags": ["learning-coach", "surface:web"],
        "metadata": metadata,
    }


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)

    @field_validator("answer")
    @classmethod
    def strip_answer(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("回答不能为空。")
        return normalized


class ForkRequest(BaseModel):
    checkpoint_id: str = Field(min_length=1, max_length=64)

    @field_validator("checkpoint_id")
    @classmethod
    def strip_checkpoint(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("checkpoint_id 不能为空。")
        return normalized


class ApplyModelConfigRequest(BaseModel):
    auth_mode: Literal["api", "cli"]
    test_id: str | None = Field(default=None, max_length=64)
    chat_model_id: str | None = Field(default=None, max_length=200)
    assessment_model_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "ApplyModelConfigRequest":
        if self.auth_mode == "api":
            if not (self.test_id or "").strip():
                raise ValueError("API 配置必须提供已通过测试的 test_id。")
        elif not (self.chat_model_id or "").strip():
            raise ValueError("CLI 配置必须提供 chat_model_id。")
        return self


class UnconfiguredRuntimeModelConfig(BaseModel):
    configured: Literal[False] = False
    error: str


class CourseChapterView(BaseModel):
    chapter_id: str
    title: str
    location: str = ""
    order: int
    chunks: int
    status: Literal["not_started", "in_progress", "completed"] = "not_started"
    score: int | None = None
    attempts: int = 0


class CourseView(BaseModel):
    course_id: str
    book_title: str
    chapters_total: int = 0
    completed_chapters: int = 0
    average_score: int | None = None
    next_chapter_id: str | None = None
    next_chapter_title: str | None = None
    updated_at: str = ""
    chapters: list[CourseChapterView] = Field(default_factory=list)


class CourseContextView(BaseModel):
    course_id: str
    book_title: str
    chapter_id: str
    chapter_title: str


class SessionView(BaseModel):
    session_id: str
    status: Literal["waiting", "completed"]
    stage: Literal[
        "diagnostic", "understanding_check", "quiz", "approval", "summary"
    ]
    topic: str
    learning_mode: LearningMode
    learning_goal: str
    learner_id: str = "local-learner"
    long_term_memory: LearnerMemoryView | None = None
    mastery_level: int = 0
    recent_errors: list[str] = Field(default_factory=list)
    context_summary: str | None = None
    context_report: ContextReport | None = None
    ingestion_report: IngestionReport | None = None
    retrieval_report: RetrievalReport | None = None
    graph_report: GraphRAGReport | None = None
    question: str | None = None
    code_exercise: CodeExerciseView | None = None
    code_practice_report: CodePracticeReport | None = None
    code_tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
    diagnostic_focus: str | None = None
    diagnostic_difficulty: str | None = None
    explanation: str | None = None
    practice_kind: str | None = None
    learning_events: list[LearningEvent] = Field(default_factory=list)
    teaching_plan: TeachingPlan | None = None
    research_evidence: ResearchEvidence | None = None
    teaching_reviews: list[ReviewFinding] = Field(default_factory=list)
    agent_handoffs: list[AgentHandoff] = Field(default_factory=list)
    safety_findings: list[dict[str, Any]] = Field(default_factory=list)
    stage_report: StageReport | None = None
    execution_approved: bool | None = None
    score: int | None = None
    feedback: str | None = None
    missing_point: str | None = None
    attempts: int = 0
    summary: str | None = None
    sources: list[StudySource] = Field(default_factory=list)
    course: CourseContextView | None = None


class PublicModelConfig(BaseModel):
    configured: bool
    chat_model_id: str | None = None
    assessment_model_id: str | None = None
    advanced_chat_model_id: str | None = None
    chat_fallback_model_id: str | None = None
    assessment_fallback_model_id: str | None = None
    embedding_model_id: str | None = None
    accepts_images: bool | None = None
    run_timeout_seconds: float | None = None
    context_model_call_limit: int | None = None
    context_tool_call_limit: int | None = None
    error: str | None = None


class LearningSessionService:
    """Run browser sessions on the existing LangGraph with in-memory state."""

    def __init__(
        self,
        *,
        models: LearningCoachModels | None = None,
        models_factory: Callable[[], LearningCoachModels] = create_model_suite,
        chat_model_id: str | None = None,
        assessment_model_id: str | None = None,
        chat_fallback_model_id: str | None = None,
        assessment_fallback_model_id: str | None = None,
        run_timeout_seconds: float | None = None,
        context_settings: LearningContextSettings | None = None,
        web_fetcher: SafeWebFetcher | None = None,
        checkpointer: Any | None = None,
        store: Any | None = None,
        runtime_config_service: RuntimeModelConfigService | None = None,
        auth_action: Callable[[str, str], int] = run_auth_action,
    ) -> None:
        self._models = models
        self._models_factory = models_factory
        self._graph: Any | None = None
        self._checkpointer = checkpointer
        self._store = store
        self._chat_model_id = chat_model_id
        self._assessment_model_id = assessment_model_id
        self._advanced_chat_model_id: str | None = None
        self._chat_fallback_model_id = chat_fallback_model_id
        self._assessment_fallback_model_id = assessment_fallback_model_id
        self._embedding_model_id: str | None = None
        self._run_timeout_seconds = (
            run_timeout_seconds
            if run_timeout_seconds is not None
            else web_run_timeout_seconds(os.environ)
        )
        if self._run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds 必须是正数。")
        self._sessions: set[str] = set()
        self._runtime_contexts: dict[str, LearningRuntimeContext] = {}
        self._session_run_locks: dict[str, asyncio.Lock] = {}
        self._session_runtimes: dict[str, RuntimeModelVersion] = {}
        self._course_corpora: OrderedDict[str, list[StudyChunkRecord]] = OrderedDict()
        self._course_sessions: dict[str, dict[str, str]] = {}
        self._context_settings = context_settings or LearningContextSettings.from_environ(
            os.environ
        )
        self._web_fetcher = web_fetcher
        if self._checkpointer is None:
            self._checkpointer = create_checkpointer(os.environ)
        if self._store is None:
            self._store = create_memory_store(os.environ)
        self._setup_lock = threading.Lock()
        self._invoke_lock = threading.Lock()
        self._runtime_config = runtime_config_service or RuntimeModelConfigService(
            runtime_builder=lambda models: build_learning_graph(
                models,
                checkpointer=self._checkpointer,
                store=self._store,
            )
        )
        self._auth_action = auth_action
        self._auth_locks = {
            "codex": threading.Lock(),
            "claude": threading.Lock(),
        }

    @property
    def runtime_config(self) -> RuntimeModelConfigService:
        return self._runtime_config

    def public_runtime_config(
        self,
    ) -> PublicRuntimeModelConfig | UnconfiguredRuntimeModelConfig:
        try:
            return self._ensure_runtime().config
        except (RuntimeError, ValueError):
            return UnconfiguredRuntimeModelConfig(
                error="尚未配置可用模型，请在本页测试并应用 API 或 CLI 模型。"
            )

    def test_runtime_config(
        self, request: ApiModelConfigInput
    ) -> TestedRuntimeModelConfig:
        return self._runtime_config.test_api_config(request)

    def apply_runtime_config(
        self, request: ApplyModelConfigRequest
    ) -> PublicRuntimeModelConfig:
        if request.auth_mode == "api":
            assert request.test_id is not None
            return self._runtime_config.apply_tested(request.test_id).config
        assert request.chat_model_id is not None
        return self._runtime_config.apply_cli(
            chat_model_id=request.chat_model_id,
            assessment_model_id=request.assessment_model_id,
        ).config

    def run_model_auth(self, provider: str, action: str) -> None:
        if provider not in self._auth_locks:
            raise ValueError("仅支持 codex 或 claude 官方 CLI。")
        if action not in {"login", "status", "logout"}:
            raise ValueError("不支持的认证动作。")
        with self._auth_locks[provider]:
            self._auth_action(provider, action)

    def create_course(
        self, *, material: MaterialInput, learner_id: str
    ) -> CourseView:
        """Ingest one book with relaxed course limits and persist its outline."""

        runtime = self._ensure_runtime()
        learner = self._normalized_learner(learner_id)
        ingestion = MaterialIngestionPipeline(
            default_loader_registry(
                web_fetcher=self._web_fetcher,
                image_model=runtime.models.chat,
                accepts_images=runtime.models.accepts_images,
            )
        ).ingest([material], limits=material.limits)
        outline = build_course_outline(
            Path(material.source_name).stem or material.source_name,
            ingestion.chunks,
        )
        self._store_course_corpus(outline.course_id, ingestion.chunks)
        record = save_course(self._store, learner, outline, now=_now_iso())
        return _course_detail_view(record)

    def list_learner_courses(self, learner_id: str) -> list[CourseView]:
        learner = self._normalized_learner(learner_id)
        return [
            _course_detail_view(record)
            for record in list_courses(self._store, learner)
        ]

    def course_detail(self, *, learner_id: str, course_id: str) -> CourseView:
        record = load_course(
            self._store, self._normalized_learner(learner_id), course_id
        )
        if record is None:
            raise LookupError("找不到指定的课程。")
        return _course_detail_view(record)

    async def create_chapter_session_events_async(
        self,
        *,
        course_id: str,
        chapter_id: str,
        learner_id: str,
        learning_mode: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Prepare a chapter session off-loop, then stream the shared graph."""

        prepared = await asyncio.to_thread(
            self._prepare_chapter_session,
            course_id,
            chapter_id,
            learner_id,
            learning_mode,
        )
        return self._events_for_initial_state(
            prepared["initial_state"],
            prepared["runtime"],
            course_context=prepared["course_context"],
        )

    def _prepare_chapter_session(
        self,
        course_id: str,
        chapter_id: str,
        learner_id: str,
        learning_mode: str | None,
    ) -> dict[str, Any]:
        learner = self._normalized_learner(learner_id)
        record = load_course(self._store, learner, course_id)
        if record is None:
            raise LookupError("找不到指定的课程。")
        chapter = next(
            (
                item
                for item in record.chapters
                if item.chapter_id == chapter_id
            ),
            None,
        )
        if chapter is None:
            raise LookupError("找不到指定的章节。")
        chunks = self._course_corpora.get(course_id)
        if chunks is None:
            raise ValueError(
                "课程语料已随服务重启清空；请重新上传同一份资料恢复学习。"
            )
        self._course_corpora.move_to_end(course_id)
        selected = chapter_chunks(chunks, chapter_id)
        initial_state: dict[str, Any] = {
            "topic": f"《{record.book_title}》{chapter.title}"[:500],
            "learning_mode": learning_mode_for_new_session(learning_mode),
            "learning_goal": (
                f"掌握《{record.book_title}》第 {chapter.order} 章：{chapter.title}"
            )[:1000],
            "learner_id": learner,
            "mastery_level": 0,
            "recent_errors": [],
            "attempts": 0,
            "study_chunks": [chunk.model_dump() for chunk in selected],
        }
        record_chapter_result(
            self._store,
            learner,
            course_id,
            chapter_id,
            status="in_progress",
            now=_now_iso(),
        )
        return {
            "initial_state": initial_state,
            "runtime": self._ensure_runtime(),
            "course_context": {
                "course_id": course_id,
                "chapter_id": chapter_id,
                "learner_id": learner,
                "book_title": record.book_title,
                "chapter_title": chapter.title,
            },
        }

    @staticmethod
    def _normalized_learner(learner_id: str) -> str:
        return (learner_id or "").strip()[:100] or "local-learner"

    def _store_course_corpus(
        self, course_id: str, chunks: list[StudyChunkRecord]
    ) -> None:
        self._course_corpora[course_id] = chunks
        self._course_corpora.move_to_end(course_id)
        while len(self._course_corpora) > MAX_COURSE_CORPORA:
            self._course_corpora.popitem(last=False)

    def _ensure_runtime(self) -> RuntimeModelVersion:
        try:
            runtime = self._runtime_config.current()
        except RuntimeError:
            runtime = None
        if runtime is not None:
            self._sync_runtime_metadata(runtime)
            return runtime

        with self._setup_lock:
            try:
                runtime = self._runtime_config.current()
            except RuntimeError:
                runtime = None
            if runtime is None:
                if self._models is None:
                    self._models = self._models_factory()
                graph = self._graph or build_learning_graph(
                    self._models,
                    checkpointer=self._checkpointer,
                    store=self._store,
                )
                chat_model_id = self._chat_model_id
                assessment_model_id = self._assessment_model_id
                if chat_model_id is None or assessment_model_id is None:
                    load_dotenv()
                    settings = ModelSettings.from_environ(os.environ)
                    chat_model_id = chat_model_id or settings.chat_model_id
                    assessment_model_id = (
                        assessment_model_id or settings.assessment_model_id
                    )
                    self._advanced_chat_model_id = settings.advanced_chat_model_id
                    self._chat_fallback_model_id = (
                        self._chat_fallback_model_id
                        or settings.chat_fallback_model_id
                    )
                    self._assessment_fallback_model_id = (
                        self._assessment_fallback_model_id
                        or settings.assessment_fallback_model_id
                    )
                auth_mode = (
                    "cli"
                    if chat_model_id.startswith(("codex_cli:", "claude_code:"))
                    and assessment_model_id.startswith(
                        ("codex_cli:", "claude_code:")
                    )
                    else "api"
                )
                runtime = self._runtime_config.install_initial(
                    models=self._models,
                    runtime=graph,
                    chat_model_id=chat_model_id,
                    assessment_model_id=assessment_model_id,
                    auth_mode=auth_mode,
                )
        self._sync_runtime_metadata(runtime)
        return runtime

    def _sync_runtime_metadata(self, runtime: RuntimeModelVersion) -> None:
        self._models = runtime.models
        self._graph = runtime.runtime
        self._chat_model_id = runtime.config.chat_model_id
        self._assessment_model_id = runtime.config.assessment_model_id

    def _ensure_graph(self) -> Any:
        return self._ensure_runtime().runtime

    def public_config(self) -> PublicModelConfig:
        try:
            graph = self._ensure_graph()
            assert graph is not None
        except (RuntimeError, ValueError) as exc:
            return PublicModelConfig(configured=False, error=str(exc))

        if self._chat_model_id is None or self._assessment_model_id is None:
            load_dotenv()
            try:
                settings = ModelSettings.from_environ(os.environ)
            except (RuntimeError, ValueError) as exc:
                return PublicModelConfig(configured=False, error=str(exc))
            self._chat_model_id = settings.chat_model_id
            self._assessment_model_id = settings.assessment_model_id
            self._advanced_chat_model_id = settings.advanced_chat_model_id
            self._chat_fallback_model_id = settings.chat_fallback_model_id
            self._assessment_fallback_model_id = (
                settings.assessment_fallback_model_id
            )

        if self._embedding_model_id is None:
            try:
                self._embedding_model_id = RagSettings.from_environ(
                    os.environ
                ).embedding_model_id
            except (RuntimeError, ValueError) as exc:
                return PublicModelConfig(configured=False, error=str(exc))

        assert self._models is not None
        return PublicModelConfig(
            configured=True,
            chat_model_id=self._chat_model_id,
            assessment_model_id=self._assessment_model_id,
            advanced_chat_model_id=self._advanced_chat_model_id,
            chat_fallback_model_id=self._chat_fallback_model_id,
            assessment_fallback_model_id=self._assessment_fallback_model_id,
            embedding_model_id=self._embedding_model_id,
            accepts_images=self._models.accepts_images,
            run_timeout_seconds=self._run_timeout_seconds,
            context_model_call_limit=self._context_settings.model_call_limit,
            context_tool_call_limit=self._context_settings.tool_call_limit,
        )

    def _initial_state(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]],
        study_material: str,
        learning_goal: str = "",
        materials: Sequence[MaterialInput] = (),
        learner_id: str = "",
        learning_mode: str | None = None,
        *,
        _runtime: RuntimeModelVersion | None = None,
    ) -> dict[str, Any]:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("学习主题不能为空。")
        if len(normalized_topic) > 500:
            raise ValueError("学习主题不能超过 500 个字符。")
        normalized_learner = learner_id.strip()[:100]

        runtime = _runtime or self._ensure_runtime()
        if image_blocks and not runtime.models.accepts_images:
            raise ValueError("当前主模型不支持图片输入，请移除图片或更换视觉模型。")

        runtime_context = create_learning_runtime_context(
            normalized_topic,
            learning_goal=learning_goal,
            settings=self._context_settings,
        )
        initial_state: dict[str, Any] = {
            "topic": normalized_topic,
            "learning_mode": learning_mode_for_new_session(learning_mode),
            "learning_goal": runtime_context.learning_goal,
            "learner_id": normalized_learner or "local-learner",
            "mastery_level": 0,
            "recent_errors": [],
            "attempts": 0,
        }
        normalized_material = normalize_study_material(study_material)
        if normalized_material:
            initial_state["study_material"] = normalized_material
            material_safety = inspect_content_safety(
                normalized_material, source="study_material"
            )
            initial_state["safety_findings"] = safety_findings_updates(
                material_safety
            )
        if materials or normalized_material:
            ingestion_materials = list(materials)
            if normalized_material:
                ingestion_materials.append(
                    MaterialInput(
                        source_name="pasted-text.txt",
                        mime_type="text/plain",
                        data=normalized_material.encode("utf-8"),
                    )
                )
            ingestion = MaterialIngestionPipeline(
                default_loader_registry(
                    web_fetcher=self._web_fetcher,
                    image_model=runtime.models.chat,
                    accepts_images=runtime.models.accepts_images,
                )
            ).ingest(ingestion_materials)
            initial_state["study_chunks"] = [
                chunk.model_dump() for chunk in ingestion.chunks
            ]
            initial_state["ingestion_report"] = ingestion.report.model_dump()
        if image_blocks:
            initial_state["diagnostic_images"] = list(image_blocks)
        return initial_state

    def create_session(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]] = (),
        study_material: str = "",
        learning_goal: str = "",
        materials: Sequence[MaterialInput] = (),
        learner_id: str = "",
        learning_mode: str | None = None,
    ) -> SessionView:
        runtime = self._ensure_runtime()
        graph = runtime.runtime
        session_id = uuid.uuid4().hex
        initial_state = self._initial_state(
            topic,
            image_blocks,
            study_material,
            learning_goal,
            materials,
            learner_id,
            learning_mode,
            _runtime=runtime,
        )
        runtime_context = create_learning_runtime_context(
            initial_state["topic"],
            learning_goal=initial_state["learning_goal"],
            settings=self._context_settings,
        )
        config = session_run_config(
            session_id,
            has_study_material=bool(
                initial_state.get("study_material")
                or initial_state.get("study_chunks")
            ),
        )

        with self._invoke_lock:
            result = graph.invoke(
                initial_state, config=config, context=runtime_context
            )
        self._sessions.add(session_id)
        self._runtime_contexts[session_id] = runtime_context
        self._session_runtimes[session_id] = runtime
        return self._view(session_id, result)

    def create_session_events(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]] = (),
        study_material: str = "",
        learning_goal: str = "",
        materials: Sequence[MaterialInput] = (),
        learner_id: str = "",
        learning_mode: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        runtime = self._ensure_runtime()
        initial_state = self._initial_state(
            topic,
            image_blocks,
            study_material,
            learning_goal,
            materials,
            learner_id,
            learning_mode,
            _runtime=runtime,
        )
        return self._events_for_initial_state(initial_state, runtime)

    async def create_session_events_async(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]] = (),
        study_material: str = "",
        learning_goal: str = "",
        materials: Sequence[MaterialInput] = (),
        learner_id: str = "",
        learning_mode: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Prepare blocking material ingestion off-loop, then stream the graph."""

        runtime = self._ensure_runtime()
        initial_state = await asyncio.to_thread(
            self._initial_state,
            topic,
            image_blocks,
            study_material,
            learning_goal,
            materials,
            learner_id,
            learning_mode,
            _runtime=runtime,
        )
        return self._events_for_initial_state(initial_state, runtime)

    def _events_for_initial_state(
        self,
        initial_state: dict[str, Any],
        runtime: RuntimeModelVersion | None = None,
        *,
        course_context: Mapping[str, str] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        session_id = uuid.uuid4().hex
        if course_context is not None:
            self._course_sessions[session_id] = dict(course_context)
        self._session_runtimes[session_id] = runtime or self._ensure_runtime()
        self._runtime_contexts[session_id] = create_learning_runtime_context(
            initial_state["topic"],
            learning_goal=initial_state["learning_goal"],
            settings=self._context_settings,
        )
        return self._graph_events(
            session_id,
            initial_state,
            register_session=True,
        )

    def answer(self, session_id: str, answer: str) -> SessionView:
        normalized_answer = self._validated_answer(session_id, answer)

        graph = self._runtime_for_session(session_id).runtime
        config = session_run_config(session_id)
        with self._invoke_lock:
            result = graph.invoke(
                Command(resume=normalized_answer),
                config=config,
                context=self._runtime_contexts[session_id],
            )
        return self._view(session_id, result)

    def answer_events(
        self, session_id: str, answer: str
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        normalized_answer = self._validated_answer(session_id, answer)
        return self._graph_events(
            session_id,
            Command(resume=normalized_answer),
            register_session=False,
        )

    def _validated_answer(self, session_id: str, answer: str) -> str:
        if session_id not in self._sessions:
            raise SessionNotFoundError("找不到该学习会话；服务重启后请重新开始。")
        normalized_answer = answer.strip()
        if not normalized_answer:
            raise ValueError("回答不能为空。")
        if len(normalized_answer) > 20_000:
            raise ValueError("回答不能超过 20000 个字符。")
        return normalized_answer

    def _runtime_for_session(self, session_id: str) -> RuntimeModelVersion:
        try:
            return self._session_runtimes[session_id]
        except KeyError as exc:
            raise SessionNotFoundError(
                "找不到该学习会话；服务重启后请重新开始。"
            ) from exc

    def session_runtime_version(self, session_id: str) -> int:
        return self._runtime_for_session(session_id).config.version

    def session_history(self, session_id: str) -> list[CheckpointMilestone]:
        if session_id not in self._sessions:
            raise SessionNotFoundError("找不到该学习会话；服务重启后请重新开始。")
        graph = self._runtime_for_session(session_id).runtime
        return list_session_checkpoints(
            graph, {"configurable": {"thread_id": f"web-{session_id}"}}
        )

    def fork_session_view(
        self, session_id: str, checkpoint_id: str
    ) -> dict[str, Any]:
        if session_id not in self._sessions:
            raise SessionNotFoundError("找不到该学习会话；服务重启后请重新开始。")
        if not checkpoint_id.strip():
            raise ValueError("checkpoint_id 不能为空。")
        runtime = self._runtime_for_session(session_id)
        graph = runtime.runtime
        fork_session_id = uuid.uuid4().hex
        fork_result = fork_session(
            graph,
            {"configurable": {"thread_id": f"web-{session_id}"}},
            checkpoint_id.strip(),
            f"web-{fork_session_id}",
        )
        runtime_context = self._runtime_contexts[session_id]
        with self._invoke_lock:
            result = graph.invoke(
                None,
                config=fork_result["fork_config"],
                context=runtime_context,
            )
        self._sessions.add(fork_session_id)
        self._runtime_contexts[fork_session_id] = runtime_context
        self._session_runtimes[fork_session_id] = runtime
        view = self._view(fork_session_id, result)
        comparison = compare_learning_states(
            fork_result["baseline"], result
        )
        return {
            "session": view,
            "forked_from": session_id,
            "checkpoint_id": checkpoint_id.strip(),
            "entry_node": fork_result["entry_node"],
            "comparison": comparison,
        }

    async def _graph_events(
        self,
        session_id: str,
        graph_input: dict[str, Any] | Command,
        *,
        register_session: bool,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        lock = self._session_run_locks.setdefault(session_id, asyncio.Lock())
        deadline = (
            asyncio.get_running_loop().time() + self._run_timeout_seconds
        )
        lock_acquired = False
        iterator: Any | None = None
        timed_out = False
        try:
            await _await_before_deadline(lock.acquire, deadline)
            lock_acquired = True
            iterator = self._unlocked_graph_events(
                session_id,
                graph_input,
                register_session=register_session,
            ).__aiter__()
            while True:
                try:
                    event = await _await_before_deadline(
                        iterator.__anext__, deadline
                    )
                except StopAsyncIteration:
                    break
                yield event
        except (TimeoutError, asyncio.TimeoutError):
            timed_out = True
            if register_session:
                self._runtime_contexts.pop(session_id, None)
                self._session_runtimes.pop(session_id, None)
                self._course_sessions.pop(session_id, None)
        finally:
            try:
                if iterator is not None:
                    await iterator.aclose()
            finally:
                if lock_acquired:
                    lock.release()
                if register_session and session_id not in self._sessions:
                    self._runtime_contexts.pop(session_id, None)
                    self._session_runtimes.pop(session_id, None)
                    self._course_sessions.pop(session_id, None)
                    if self._session_run_locks.get(session_id) is lock:
                        self._session_run_locks.pop(session_id, None)
        if timed_out:
            yield "error", {
                "code": "run_timeout",
                "message": "本次模型运行超时，请重试。",
            }
            yield "done", {"ok": False}

    async def _unlocked_graph_events(
        self,
        session_id: str,
        graph_input: dict[str, Any] | Command,
        *,
        register_session: bool,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        graph = self._runtime_for_session(session_id).runtime
        config = session_run_config(
            session_id,
            has_study_material=(
                bool(graph_input.get("study_material"))
                or bool(graph_input.get("study_chunks"))
                if isinstance(graph_input, dict)
                else None
            ),
        )
        latest_state: dict[str, Any] | None = None
        latest_interrupts: Sequence[Any] = ()
        try:
            async for part in graph.astream(
                graph_input,
                config=config,
                stream_mode=["custom", "values"],
                version="v2",
                subgraphs=True,
                context=self._runtime_contexts[session_id],
            ):
                if part["type"] == "custom":
                    event = dict(part["data"])
                    event_name = str(event.pop("event", "status"))
                    yield event_name, event
                elif part["type"] == "values" and not part.get("ns"):
                    latest_state = dict(part["data"])
                    if part.get("interrupts"):
                        latest_interrupts = part["interrupts"]
        except (TimeoutError, asyncio.TimeoutError):
            raise
        except asyncio.CancelledError:
            if register_session:
                self._runtime_contexts.pop(session_id, None)
                self._session_runtimes.pop(session_id, None)
                self._course_sessions.pop(session_id, None)
            raise
        except Exception:
            if register_session:
                self._runtime_contexts.pop(session_id, None)
                self._session_runtimes.pop(session_id, None)
                self._course_sessions.pop(session_id, None)
            yield "error", {
                "code": "run_failed",
                "message": "本次模型运行失败，请检查配置后重试。",
            }
            yield "done", {"ok": False}
            return

        if latest_state is None:
            if register_session:
                self._runtime_contexts.pop(session_id, None)
                self._session_runtimes.pop(session_id, None)
                self._course_sessions.pop(session_id, None)
            yield "error", {
                "code": "empty_run",
                "message": "本次模型运行没有返回状态，请重试。",
            }
            yield "done", {"ok": False}
            return
        if latest_interrupts:
            latest_state["__interrupt__"] = latest_interrupts
        course_context = self._course_sessions.get(session_id)
        if course_context is not None and not latest_interrupts:
            record_chapter_result(
                self._store,
                course_context["learner_id"],
                course_context["course_id"],
                course_context["chapter_id"],
                status="completed",
                score=latest_state.get("score"),
                attempts=int(latest_state.get("attempts") or 0),
                now=_now_iso(),
            )
        if register_session:
            self._sessions.add(session_id)
        view = self._view(session_id, latest_state)
        if course_context is not None:
            view.course = CourseContextView(
                course_id=course_context["course_id"],
                book_title=course_context["book_title"],
                chapter_id=course_context["chapter_id"],
                chapter_title=course_context["chapter_title"],
            )
        yield "state", view.model_dump(mode="json")
        yield "done", {"ok": True}

    @staticmethod
    def _view(session_id: str, state: dict[str, Any]) -> SessionView:
        exercise = (
            CodeExercise.model_validate(state["code_exercise"])
            if state.get("code_exercise")
            else None
        )
        public_exercise = (
            CodeExerciseView.from_exercise(exercise)
            if exercise is not None
            else None
        )
        interrupts = state.get("__interrupt__", ())
        if interrupts:
            payload = interrupts[0].value
            kind = payload.get("kind", "quiz")
            stage = (
                "diagnostic"
                if kind == "diagnostic"
                else "understanding_check"
                if kind == "understanding_check"
                else "approval"
                if kind == "approval"
                else "quiz"
            )
            return SessionView(
                session_id=session_id,
                status="waiting",
                stage=stage,
                topic=state["topic"],
                learning_mode=learning_mode_for_state(state),
                learning_goal=state.get(
                    "learning_goal", f"掌握主题：{state['topic']}"
                ),
                learner_id=state.get("learner_id", "local-learner"),
                long_term_memory=state.get("long_term_memory"),
                mastery_level=state.get("mastery_level", state.get("score", 0) or 0),
                recent_errors=state.get("recent_errors", []),
                context_summary=state.get("context_summary"),
                context_report=state.get("context_report"),
                ingestion_report=state.get("ingestion_report"),
                retrieval_report=state.get("retrieval_report"),
                graph_report=state.get("graph_report"),
                question=str(payload.get("question", "")),
                code_exercise=public_exercise,
                code_practice_report=state.get("code_practice_report"),
                code_tool_trace=state.get("code_tool_trace", []),
                diagnostic_focus=state.get("diagnostic_focus"),
                diagnostic_difficulty=state.get("diagnostic_difficulty"),
                explanation=state.get("explanation"),
                practice_kind=state.get("practice_kind"),
                learning_events=state.get("learning_events", []),
                teaching_plan=state.get("teaching_plan"),
                research_evidence=state.get("research_evidence"),
                teaching_reviews=state.get("teaching_reviews", []),
                agent_handoffs=state.get("agent_handoffs", []),
                safety_findings=state.get("safety_findings", []),
                stage_report=state.get("stage_report"),
                execution_approved=state.get("execution_approved"),
                score=state.get("score"),
                feedback=state.get("feedback"),
                missing_point=state.get("missing_point"),
                attempts=state.get("attempts", 0),
                sources=state.get("explanation_sources", []),
            )
        return SessionView(
            session_id=session_id,
            status="completed",
            stage="summary",
            topic=state["topic"],
            learning_mode=learning_mode_for_state(state),
            learning_goal=state.get(
                "learning_goal", f"掌握主题：{state['topic']}"
            ),
            learner_id=state.get("learner_id", "local-learner"),
            long_term_memory=state.get("long_term_memory"),
            mastery_level=state.get("mastery_level", state.get("score", 0) or 0),
            recent_errors=state.get("recent_errors", []),
            context_summary=state.get("context_summary"),
            context_report=state.get("context_report"),
            ingestion_report=state.get("ingestion_report"),
            retrieval_report=state.get("retrieval_report"),
            graph_report=state.get("graph_report"),
            code_exercise=public_exercise,
            code_practice_report=state.get("code_practice_report"),
            code_tool_trace=state.get("code_tool_trace", []),
            diagnostic_focus=state.get("diagnostic_focus"),
            diagnostic_difficulty=state.get("diagnostic_difficulty"),
            explanation=state.get("explanation"),
            practice_kind=state.get("practice_kind"),
            learning_events=state.get("learning_events", []),
            teaching_plan=state.get("teaching_plan"),
            research_evidence=state.get("research_evidence"),
            teaching_reviews=state.get("teaching_reviews", []),
            agent_handoffs=state.get("agent_handoffs", []),
            safety_findings=state.get("safety_findings", []),
            stage_report=state.get("stage_report"),
            execution_approved=state.get("execution_approved"),
            score=state.get("score"),
            feedback=state.get("feedback"),
            missing_point=state.get("missing_point"),
            attempts=state.get("attempts", 0),
            summary=state.get("summary"),
            sources=state.get("explanation_sources", []),
        )


def _course_detail_view(record: CourseRecord) -> CourseView:
    summary = course_summary(record)
    chapters = [
        CourseChapterView(
            chapter_id=chapter.chapter_id,
            title=chapter.title,
            location=chapter.location,
            order=chapter.order,
            chunks=chapter.chunks,
            status=entry.status if entry is not None else "not_started",
            score=entry.score if entry is not None else None,
            attempts=entry.attempts if entry is not None else 0,
        )
        for chapter in record.chapters
        for entry in (record.progress.get(chapter.chapter_id),)
    ]
    return CourseView(**summary, chapters=chapters)


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


async def _session_view_from_events(
    events: AsyncIterator[tuple[str, dict[str, Any]]],
) -> SessionView:
    state_payload: dict[str, Any] | None = None
    error_payload: dict[str, Any] | None = None
    async for event, payload in events:
        if event == "state":
            state_payload = payload
        elif event == "error":
            error_payload = payload

    if error_payload is not None:
        status_code = 504 if error_payload.get("code") == "run_timeout" else 503
        raise HTTPException(status_code=status_code, detail=error_payload)
    if state_payload is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "empty_run",
                "message": "本次模型运行没有返回状态，请重试。",
            },
        )
    return SessionView.model_validate(state_payload)


async def _read_material_inputs(
    uploads: Sequence[UploadFile],
    source_urls: str,
) -> list[MaterialInput]:
    materials: list[MaterialInput] = []
    try:
        for upload in uploads:
            content = await upload.read(MAX_SINGLE_MATERIAL_BYTES + 1)
            materials.append(
                MaterialInput(
                    source_name=upload.filename or "material",
                    mime_type=upload.content_type or "application/octet-stream",
                    data=content,
                )
            )
        urls = [line.strip() for line in source_urls.splitlines() if line.strip()]
        materials.extend(material_inputs_from_urls(urls))
        validate_material_batch(materials)
        return materials
    finally:
        for upload in uploads:
            await upload.close()


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host.lower() == "localhost"
    if not is_loopback:
        raise HTTPException(
            status_code=403,
            detail="模型设置与认证接口仅允许从本机访问。",
        )


def _require_sensitive_write(request: Request) -> None:
    _require_loopback(request)
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("application/json"):
        raise HTTPException(
            status_code=403,
            detail="模型设置与认证写操作只接受同源 JSON 请求。",
        )
    origin = request.headers.get("origin", "").rstrip("/")
    expected_origin = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip(
        "/"
    )
    if not origin or origin != expected_origin:
        raise HTTPException(
            status_code=403,
            detail="模型设置与认证写操作只接受同源 JSON 请求。",
        )


def create_app(*, service: LearningSessionService | None = None) -> FastAPI:
    session_service = service or LearningSessionService()
    application = FastAPI(
        title="Learning Coach Web",
        description="诊断、讲解、练习、评价和补救的本地 AI 学习页面。",
        version="0.1.0",
    )
    application.state.session_service = session_service
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/settings", include_in_schema=False)
    def settings_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "settings.html")

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get(
        "/api/config",
        response_model=PublicModelConfig,
        response_model_exclude_none=True,
    )
    def config() -> PublicModelConfig:
        return session_service.public_config()

    @application.get(
        "/api/model-config",
        response_model=PublicRuntimeModelConfig | UnconfiguredRuntimeModelConfig,
    )
    def model_config(
        request: Request,
    ) -> PublicRuntimeModelConfig | UnconfiguredRuntimeModelConfig:
        _require_loopback(request)
        try:
            return session_service.public_runtime_config()
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post(
        "/api/model-config/test",
        response_model=TestedRuntimeModelConfig,
    )
    def test_model_config(
        request: Request,
        payload: ApiModelConfigInput,
    ) -> TestedRuntimeModelConfig:
        _require_sensitive_write(request)
        try:
            return session_service.test_runtime_config(payload)
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.put(
        "/api/model-config",
        response_model=PublicRuntimeModelConfig,
    )
    def apply_model_config(
        request: Request,
        payload: ApplyModelConfigRequest,
    ) -> PublicRuntimeModelConfig:
        _require_sensitive_write(request)
        try:
            return session_service.apply_runtime_config(payload)
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.get("/api/model-auth/{provider}/status")
    async def model_auth_status(
        provider: Literal["codex", "claude"],
        request: Request,
    ) -> dict[str, Any]:
        _require_loopback(request)
        try:
            await run_in_threadpool(
                session_service.run_model_auth, provider, "status"
            )
            return {"provider": provider, "action": "status", "ok": True}
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post("/api/model-auth/{provider}/{action}")
    async def model_auth_write(
        provider: Literal["codex", "claude"],
        action: Literal["login", "logout"],
        request: Request,
    ) -> dict[str, Any]:
        _require_sensitive_write(request)
        try:
            await run_in_threadpool(
                session_service.run_model_auth, provider, action
            )
            return {"provider": provider, "action": action, "ok": True}
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post("/api/courses", response_model=CourseView, status_code=201)
    async def create_course(
        request: Request,
        learner_id: str = Form(default=""),
        book: UploadFile = File(...),
    ) -> CourseView:
        _require_loopback(request)
        try:
            data = await book.read(COURSE_MATERIAL_LIMITS.max_single_bytes + 1)
            material = MaterialInput(
                source_name=book.filename or "book",
                mime_type=book.content_type or "application/octet-stream",
                data=data,
                limits=COURSE_MATERIAL_LIMITS,
            )
            return await run_in_threadpool(
                session_service.create_course,
                material=material,
                learner_id=learner_id,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise
        finally:
            await book.close()

    @application.get(
        "/api/learners/{learner_id}/courses",
        response_model=list[CourseView],
    )
    def list_learner_courses(
        learner_id: str,
        request: Request,
    ) -> list[CourseView]:
        _require_loopback(request)
        return session_service.list_learner_courses(learner_id)

    @application.get("/api/courses/{course_id}", response_model=CourseView)
    def course_detail(
        course_id: str,
        request: Request,
        learner_id: str = "",
    ) -> CourseView:
        _require_loopback(request)
        try:
            return session_service.course_detail(
                learner_id=learner_id,
                course_id=course_id,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post(
        "/api/courses/{course_id}/chapters/{chapter_id}/sessions/stream",
        status_code=201,
    )
    async def start_chapter_session_stream(
        course_id: str,
        chapter_id: str,
        request: Request,
        learner_id: str = Form(default=""),
        learning_mode: str = Form(default="teach_first"),
    ) -> StreamingResponse:
        _require_loopback(request)
        try:
            events = await session_service.create_chapter_session_events_async(
                course_id=course_id,
                chapter_id=chapter_id,
                learner_id=learner_id,
                learning_mode=learning_mode,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise

        async def chapter_content() -> AsyncIterator[str]:
            async for event, payload in events:
                yield _sse(event, payload)

        return StreamingResponse(
            chapter_content(),
            status_code=201,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post(
        "/api/sessions",
        response_model=SessionView,
        status_code=201,
    )
    async def start_session(
        topic: str = Form(...),
        learning_mode: LearningMode = Form(default="teach_first"),
        learning_goal: str = Form(default=""),
        learner_id: str = Form(default=""),
        image: UploadFile | None = File(default=None),
        materials: list[UploadFile] | None = File(default=None),
        study_material: str = Form(default=""),
        source_urls: str = Form(default=""),
    ) -> SessionView:
        image_blocks: list[dict[str, Any]] = []
        try:
            if image is not None:
                image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
                image_blocks.append(
                    image_bytes_content_block(
                        image_bytes,
                        image.content_type or "application/octet-stream",
                    )
                )
            material_inputs = await _read_material_inputs(
                materials or [], source_urls
            )
            events = await session_service.create_session_events_async(
                topic,
                image_blocks,
                study_material,
                learning_goal,
                material_inputs,
                learner_id,
                learning_mode,
            )
            return await _session_view_from_events(events)
        except Exception as exc:
            _raise_http_error(exc)
            raise
        finally:
            if image is not None:
                await image.close()

    @application.post("/api/sessions/stream", status_code=201)
    async def start_session_stream(
        topic: str = Form(...),
        learning_mode: LearningMode = Form(default="teach_first"),
        learning_goal: str = Form(default=""),
        learner_id: str = Form(default=""),
        image: UploadFile | None = File(default=None),
        materials: list[UploadFile] | None = File(default=None),
        study_material: str = Form(default=""),
        source_urls: str = Form(default=""),
    ) -> StreamingResponse:
        image_blocks: list[dict[str, Any]] = []
        try:
            if image is not None:
                image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
                image_blocks.append(
                    image_bytes_content_block(
                        image_bytes,
                        image.content_type or "application/octet-stream",
                    )
                )
            material_inputs = await _read_material_inputs(
                materials or [], source_urls
            )
            events = await session_service.create_session_events_async(
                topic,
                image_blocks,
                study_material,
                learning_goal,
                material_inputs,
                learner_id,
                learning_mode,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise
        finally:
            if image is not None:
                await image.close()

        async def content() -> AsyncIterator[str]:
            async for event, payload in events:
                yield _sse(event, payload)

        return StreamingResponse(
            content(),
            status_code=201,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post(
        "/api/sessions/{session_id}/answers",
        response_model=SessionView,
    )
    async def submit_answer(
        session_id: str,
        request: AnswerRequest,
    ) -> SessionView:
        try:
            events = session_service.answer_events(session_id, request.answer)
            return await _session_view_from_events(events)
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post("/api/sessions/{session_id}/answers/stream")
    async def submit_answer_stream(
        session_id: str,
        request: AnswerRequest,
    ) -> StreamingResponse:
        try:
            events = session_service.answer_events(session_id, request.answer)
        except Exception as exc:
            _raise_http_error(exc)
            raise

        async def content() -> AsyncIterator[str]:
            async for event, payload in events:
                yield _sse(event, payload)

        return StreamingResponse(
            content(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.get(
        "/api/sessions/{session_id}/history",
        response_model=list[CheckpointMilestone],
    )
    def session_history(session_id: str) -> list[CheckpointMilestone]:
        try:
            return session_service.session_history(session_id)
        except Exception as exc:
            _raise_http_error(exc)
            raise

    @application.post("/api/sessions/{session_id}/fork")
    async def fork_session_endpoint(
        session_id: str,
        request: ForkRequest,
    ) -> dict[str, Any]:
        try:
            return await run_in_threadpool(
                session_service.fork_session_view,
                session_id,
                request.checkpoint_id,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise

    return application


app = create_app()
