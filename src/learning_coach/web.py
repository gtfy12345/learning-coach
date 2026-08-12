import asyncio
import json
import os
import threading
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field, field_validator

from learning_coach.graph import build_learning_graph
from learning_coach.media import MAX_IMAGE_BYTES, image_bytes_content_block
from learning_coach.model import LearningCoachModels, ModelSettings, create_model_suite
from learning_coach.retrieval import normalize_study_material
from learning_coach.schemas import StudySource

STATIC_DIR = Path(__file__).with_name("static")
DEFAULT_WEB_RUN_TIMEOUT_SECONDS = 120.0


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


class SessionView(BaseModel):
    session_id: str
    status: Literal["waiting", "completed"]
    stage: Literal["diagnostic", "quiz", "summary"]
    topic: str
    question: str | None = None
    diagnostic_focus: str | None = None
    diagnostic_difficulty: str | None = None
    explanation: str | None = None
    score: int | None = None
    feedback: str | None = None
    missing_point: str | None = None
    attempts: int = 0
    summary: str | None = None
    sources: list[StudySource] = Field(default_factory=list)


class PublicModelConfig(BaseModel):
    configured: bool
    chat_model_id: str | None = None
    assessment_model_id: str | None = None
    chat_fallback_model_id: str | None = None
    assessment_fallback_model_id: str | None = None
    accepts_images: bool | None = None
    run_timeout_seconds: float | None = None
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
    ) -> None:
        self._models = models
        self._models_factory = models_factory
        self._graph: Any | None = None
        self._chat_model_id = chat_model_id
        self._assessment_model_id = assessment_model_id
        self._chat_fallback_model_id = chat_fallback_model_id
        self._assessment_fallback_model_id = assessment_fallback_model_id
        self._run_timeout_seconds = (
            run_timeout_seconds
            if run_timeout_seconds is not None
            else web_run_timeout_seconds(os.environ)
        )
        if self._run_timeout_seconds <= 0:
            raise ValueError("run_timeout_seconds 必须是正数。")
        self._sessions: set[str] = set()
        self._setup_lock = threading.Lock()
        self._invoke_lock = threading.Lock()

    def _ensure_graph(self) -> Any:
        if self._graph is not None:
            return self._graph
        with self._setup_lock:
            if self._graph is None:
                if self._models is None:
                    self._models = self._models_factory()
                self._graph = build_learning_graph(self._models)
        return self._graph

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
            self._chat_fallback_model_id = settings.chat_fallback_model_id
            self._assessment_fallback_model_id = (
                settings.assessment_fallback_model_id
            )

        assert self._models is not None
        return PublicModelConfig(
            configured=True,
            chat_model_id=self._chat_model_id,
            assessment_model_id=self._assessment_model_id,
            chat_fallback_model_id=self._chat_fallback_model_id,
            assessment_fallback_model_id=self._assessment_fallback_model_id,
            accepts_images=self._models.accepts_images,
            run_timeout_seconds=self._run_timeout_seconds,
        )

    def _initial_state(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]],
        study_material: str,
    ) -> dict[str, Any]:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("学习主题不能为空。")
        if len(normalized_topic) > 500:
            raise ValueError("学习主题不能超过 500 个字符。")

        self._ensure_graph()
        assert self._models is not None
        if image_blocks and not self._models.accepts_images:
            raise ValueError("当前主模型不支持图片输入，请移除图片或更换视觉模型。")

        initial_state: dict[str, Any] = {
            "topic": normalized_topic,
            "attempts": 0,
        }
        normalized_material = normalize_study_material(study_material)
        if normalized_material:
            initial_state["study_material"] = normalized_material
        if image_blocks:
            initial_state["diagnostic_images"] = list(image_blocks)
        return initial_state

    def create_session(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]] = (),
        study_material: str = "",
    ) -> SessionView:
        graph = self._ensure_graph()
        session_id = uuid.uuid4().hex
        initial_state = self._initial_state(topic, image_blocks, study_material)
        config = session_run_config(
            session_id,
            has_study_material=bool(initial_state.get("study_material")),
        )

        with self._invoke_lock:
            result = graph.invoke(initial_state, config=config)
        self._sessions.add(session_id)
        return self._view(session_id, result)

    def create_session_events(
        self,
        topic: str,
        image_blocks: Sequence[dict[str, Any]] = (),
        study_material: str = "",
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        initial_state = self._initial_state(topic, image_blocks, study_material)
        session_id = uuid.uuid4().hex
        return self._graph_events(
            session_id,
            initial_state,
            register_session=True,
        )

    def answer(self, session_id: str, answer: str) -> SessionView:
        normalized_answer = self._validated_answer(session_id, answer)

        graph = self._ensure_graph()
        config = session_run_config(session_id)
        with self._invoke_lock:
            result = graph.invoke(Command(resume=normalized_answer), config=config)
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

    async def _graph_events(
        self,
        session_id: str,
        graph_input: dict[str, Any] | Command,
        *,
        register_session: bool,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        graph = self._ensure_graph()
        config = session_run_config(
            session_id,
            has_study_material=(
                bool(graph_input.get("study_material"))
                if isinstance(graph_input, dict)
                else None
            ),
        )
        latest_state: dict[str, Any] | None = None
        latest_interrupts: Sequence[Any] = ()
        try:
            async with asyncio.timeout(self._run_timeout_seconds):
                async for part in graph.astream(
                    graph_input,
                    config=config,
                    stream_mode=["custom", "values"],
                    version="v2",
                ):
                    if part["type"] == "custom":
                        event = dict(part["data"])
                        event_name = str(event.pop("event", "status"))
                        yield event_name, event
                    elif part["type"] == "values":
                        latest_state = dict(part["data"])
                        if part.get("interrupts"):
                            latest_interrupts = part["interrupts"]
        except TimeoutError:
            yield "error", {
                "code": "run_timeout",
                "message": "本次模型运行超时，请重试。",
            }
            yield "done", {"ok": False}
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            yield "error", {
                "code": "run_failed",
                "message": "本次模型运行失败，请检查配置后重试。",
            }
            yield "done", {"ok": False}
            return

        if latest_state is None:
            yield "error", {
                "code": "empty_run",
                "message": "本次模型运行没有返回状态，请重试。",
            }
            yield "done", {"ok": False}
            return
        if latest_interrupts:
            latest_state["__interrupt__"] = latest_interrupts
        if register_session:
            self._sessions.add(session_id)
        view = self._view(session_id, latest_state)
        yield "state", view.model_dump(mode="json")
        yield "done", {"ok": True}

    @staticmethod
    def _view(session_id: str, state: dict[str, Any]) -> SessionView:
        interrupts = state.get("__interrupt__", ())
        if interrupts:
            payload = interrupts[0].value
            stage = payload.get("kind", "quiz")
            return SessionView(
                session_id=session_id,
                status="waiting",
                stage="diagnostic" if stage == "diagnostic" else "quiz",
                topic=state["topic"],
                question=str(payload.get("question", "")),
                diagnostic_focus=state.get("diagnostic_focus"),
                diagnostic_difficulty=state.get("diagnostic_difficulty"),
                explanation=state.get("explanation"),
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
            diagnostic_focus=state.get("diagnostic_focus"),
            diagnostic_difficulty=state.get("diagnostic_difficulty"),
            explanation=state.get("explanation"),
            score=state.get("score"),
            feedback=state.get("feedback"),
            missing_point=state.get("missing_point"),
            attempts=state.get("attempts", 0),
            summary=state.get("summary"),
            sources=state.get("explanation_sources", []),
        )


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    raise exc


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


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

    @application.post(
        "/api/sessions",
        response_model=SessionView,
        status_code=201,
    )
    async def start_session(
        topic: str = Form(...),
        image: UploadFile | None = File(default=None),
        study_material: str = Form(default=""),
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
            return await run_in_threadpool(
                session_service.create_session,
                topic,
                image_blocks,
                study_material,
            )
        except Exception as exc:
            _raise_http_error(exc)
            raise
        finally:
            if image is not None:
                await image.close()

    @application.post("/api/sessions/stream", status_code=201)
    async def start_session_stream(
        topic: str = Form(...),
        image: UploadFile | None = File(default=None),
        study_material: str = Form(default=""),
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
            events = session_service.create_session_events(
                topic, image_blocks, study_material
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
            return await run_in_threadpool(
                session_service.answer, session_id, request.answer
            )
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

    return application


app = create_app()
