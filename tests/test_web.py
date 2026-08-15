import asyncio
import json
import time
from typing import Any

import pytest
import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from learning_coach.model import LearningCoachModels
from learning_coach.loaders import SafeWebFetcher
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.web import (
    LearningSessionService,
    create_app,
    session_run_config,
    web_run_timeout_seconds,
)


class FakeStructuredModel:
    def __init__(self, owner: "FakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, messages: Any) -> Diagnostic | Assessment:
        if self.schema is Diagnostic:
            self.owner.diagnostic_messages = (
                list(messages.to_messages())
                if hasattr(messages, "to_messages")
                else list(messages)
            )
            return Diagnostic(
                question="StateGraph 的条件边负责什么？",
                focus="条件路由",
                difficulty="foundation",
            )
        score = next(self.owner.scores)
        return Assessment(
            score=score,
            feedback="路由方向正确，但还要说明状态依据。",
            missing_point="条件函数应读取结构化状态。",
        )


class FakeChatModel:
    def __init__(self, scores: tuple[int, ...] = (86,)) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.scores = iter(scores)
        responses = [
            "条件边根据状态选择下一节点。",
            "请说明 route_after_assessment 应返回什么。",
        ]
        if len(scores) > 1:
            responses.extend(
                [
                    "补充讲解：路由函数读取 score 和 attempts。",
                    "score 为 70 且 attempts 为 1 时应该走哪条边？",
                ]
            )
        responses.append("你已经掌握条件路由，下一步练习并行状态合并。")
        self.responses = iter(responses)
        self.diagnostic_messages: list[Any] = []
        self.text_messages: list[list[Any]] = []

    def invoke(self, messages: Any) -> AIMessage:
        self.text_messages.append(
            list(messages.to_messages())
            if hasattr(messages, "to_messages")
            else list(messages)
        )
        return AIMessage(content=next(self.responses))

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        return FakeStructuredModel(self, schema)


def make_client(
    *,
    scores: tuple[int, ...] = (86,),
    run_timeout_seconds: float = 120,
    web_fetcher: SafeWebFetcher | None = None,
) -> tuple[TestClient, FakeChatModel]:
    model = FakeChatModel(scores)
    models = LearningCoachModels.from_models(model)
    service = LearningSessionService(
        models=models,
        chat_model_id="fake:coach",
        assessment_model_id="fake:assessment",
        run_timeout_seconds=run_timeout_seconds,
        web_fetcher=web_fetcher,
    )
    return TestClient(create_app(service=service)), model


def test_home_page_exposes_the_learning_product() -> None:
    client, _ = make_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "AI 学习教练" in response.text
    assert "开始诊断" in response.text


def test_web_session_runs_diagnosis_quiz_and_summary() -> None:
    client, _ = make_client()

    started = client.post("/api/sessions", data={"topic": "LangGraph 条件边"})
    assert started.status_code == 201
    first = started.json()
    assert first["status"] == "waiting"
    assert first["stage"] == "diagnostic"
    assert first["question"] == "StateGraph 的条件边负责什么？"
    assert first["learning_goal"] == "掌握主题：LangGraph 条件边"
    assert first["mastery_level"] == 0
    assert first["recent_errors"] == []

    diagnostic = client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "它根据状态选择节点。"},
    )
    assert diagnostic.status_code == 200
    second = diagnostic.json()
    assert second["stage"] == "quiz"
    assert second["explanation"] == "条件边根据状态选择下一节点。"
    assert "route_after_assessment" in second["question"]
    assert second["context_report"]["mode"] == "lcel"
    assert second["context_report"]["model_call_limit"] == 3
    assert second["practice_kind"] == "text"
    assert {event["node"] for event in second["learning_events"]} == {
        "teach",
        "prepare_practice",
    }
    assert second["teaching_plan"]["uses_research"] is False
    assert second["teaching_plan"]["review_dimensions"] == [
        "grounding",
        "clarity",
    ]
    assert second["teaching_reviews"]
    assert all(item["passed"] for item in second["teaching_reviews"])
    handoff_targets = {
        item["to_agent"] for item in second["agent_handoffs"]
    }
    assert "review" in handoff_targets
    assert "quiz" in handoff_targets

    quiz = client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "返回 retry 或 finish。"},
    )
    assert quiz.status_code == 200
    final = quiz.json()
    assert final["status"] == "completed"
    assert final["stage"] == "summary"
    assert final["score"] == 86
    assert final["mastery_level"] == 86
    assert "下一步" in final["summary"]


def test_web_code_practice_runs_tests_without_exposing_hidden_cases() -> None:
    client, _ = make_client()

    started = client.post(
        "/api/sessions", data={"topic": "Python 函数"}
    ).json()
    taught = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "函数接收参数并返回结果。"},
    ).json()

    assert taught["stage"] == "quiz"
    assert taught["practice_kind"] == "code"
    assert taught["code_exercise"]["entrypoint"] == "clamp_score"
    assert "tests" not in taught["code_exercise"]
    assert taught["code_exercise"]["total_test_count"] == 4
    assert taught["code_exercise"]["visible_test_count"] == 2

    submitted = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={
            "answer": "def clamp_score(score):\n    return min(100, max(0, score))"
        },
    ).json()

    assert submitted["status"] == "waiting"
    assert submitted["stage"] == "approval"
    assert "批准" in submitted["question"]

    completed = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "approve"},
    ).json()

    assert completed["status"] == "completed"
    assert completed["score"] == 100
    assert completed["code_practice_report"]["passed_tests"] == 4
    assert completed["code_tool_trace"][0]["tool_name"] == "run_code_tests"
    assert "/Users/" not in json.dumps(completed)


def test_stream_emits_safe_code_practice_events() -> None:
    client, _ = make_client()
    started = client.post(
        "/api/sessions/stream", data={"topic": "Python 函数"}
    )
    start_state = next(
        payload for event, payload in _sse_events(started) if event == "state"
    )

    taught = client.post(
        f"/api/sessions/{start_state['session_id']}/answers/stream",
        json={"answer": "函数返回计算结果。"},
    )
    events = _sse_events(taught)
    generated = next(
        payload
        for event, payload in events
        if event == "code_practice" and payload["stage"] == "generated"
    )

    assert generated["exercise"]["entrypoint"] == "clamp_score"
    assert "tests" not in generated["exercise"]


def test_web_accepts_learning_goal_and_exposes_context_progress() -> None:
    client, _ = make_client(scores=(60, 88))

    started = client.post(
        "/api/sessions",
        data={
            "topic": "LangGraph 条件边",
            "learning_goal": "能独立实现有界补救流程",
        },
    ).json()
    taught = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "根据状态选择节点。"},
    ).json()
    assessed = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "返回节点名称。"},
    ).json()

    assert started["learning_goal"] == "能独立实现有界补救流程"
    assert taught["context_summary"].startswith(
        "学习目标：能独立实现有界补救流程"
    )
    assert assessed["mastery_level"] == 60
    assert assessed["recent_errors"] == ["条件函数应读取结构化状态。"]
    assert "60/100" in assessed["context_summary"]
    assert assessed["context_report"]["model_calls"] == 1


def test_web_session_grounds_teaching_in_optional_study_material() -> None:
    client, model = make_client()
    started = client.post(
        "/api/sessions",
        data={
            "topic": "LangGraph 条件边",
            "study_material": (
                "条件边读取结构化 State，并把执行路由到 retry 或 finish 节点。"
            ),
        },
    ).json()

    taught = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "它根据状态选择节点。"},
    )

    assert taught.status_code == 200
    payload = taught.json()
    assert payload["sources"]
    assert payload["sources"][0]["source_id"].startswith("material-1#chunk-")
    assert payload["retrieval_report"]["embedding_model_id"] == "local:hash-v1"
    assert len(payload["retrieval_report"]["attempts"]) <= 2
    assert "vector" not in json.dumps(payload["retrieval_report"])
    assert "retry 或 finish" in model.text_messages[0][1].content


def test_web_ingests_multiple_files_and_webpage_with_safe_report() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=(
                "<html><body><h1>补救循环</h1>"
                "<p>retry 分支必须受 attempts 上限约束。</p></body></html>"
            ).encode(),
            request=request,
        )

    http_client = httpx.Client(
        transport=httpx.MockTransport(handle), follow_redirects=False
    )
    fetcher = SafeWebFetcher(
        client=http_client,
        resolver=lambda host: ["93.184.216.34"],
    )
    client, model = make_client(web_fetcher=fetcher)

    started = client.post(
        "/api/sessions",
        data={
            "topic": "LangGraph retry attempts",
            "source_urls": "https://example.com/course/remedial",
        },
        files=[
            (
                "materials",
                (
                    "graph.py",
                    b"def route(score):\n    return 'retry' if score < 80 else 'finish'\n",
                    "text/x-python",
                ),
            ),
            (
                "materials",
                (
                    "notes.md",
                    "# 条件边\nattempts 限制补救次数。".encode(),
                    "text/markdown",
                ),
            ),
        ],
    )

    assert started.status_code == 201
    state = started.json()
    report = state["ingestion_report"]
    assert report["sources_received"] == 3
    assert report["sources_added"] == 3
    assert report["errors"] == []
    assert "retry" not in json.dumps(report, ensure_ascii=False)

    taught = client.post(
        f"/api/sessions/{state['session_id']}/answers",
        json={"answer": "根据 score 和 attempts 选择。"},
    ).json()
    assert taught["sources"]
    assert taught["sources"][0]["source_name"] in {
        "graph.py",
        "notes.md",
        "remedial",
    }
    assert taught["sources"][0]["location"]
    assert "attempts" in model.text_messages[0][1].content
    http_client.close()


def test_stream_session_returns_ingestion_report_for_uploaded_material() -> None:
    client, _ = make_client()

    response = client.post(
        "/api/sessions/stream",
        data={"topic": "Reducer"},
        files={
            "materials": (
                "lesson.txt",
                "Reducer 合并并行状态。".encode(),
                "text/plain",
            )
        },
    )

    events = _sse_events(response)
    state = next(payload for event, payload in events if event == "state")
    assert state["ingestion_report"]["sources_added"] == 1
    assert state["ingestion_report"]["sources"][0]["source_name"] == "lesson.txt"


def test_web_rejects_too_many_materials_before_starting_session() -> None:
    client, _ = make_client()
    files = [
        ("materials", (f"lesson-{index}.txt", b"text", "text/plain"))
        for index in range(11)
    ]

    response = client.post(
        "/api/sessions",
        data={"topic": "Limits"},
        files=files,
    )

    assert response.status_code == 422
    assert "资料数量" in response.json()["detail"]


def test_web_session_exposes_bounded_remedial_round() -> None:
    client, _ = make_client(scores=(60, 88))
    started = client.post("/api/sessions", data={"topic": "条件路由"}).json()

    client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "根据条件决定。"},
    )
    retry = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "返回节点名字。"},
    ).json()

    assert retry["status"] == "waiting"
    assert retry["stage"] == "quiz"
    assert retry["score"] == 60
    assert retry["attempts"] == 1
    assert retry["explanation"].startswith("补充讲解")

    final = client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "读取 score 和 attempts 决定。"},
    ).json()
    assert final["status"] == "completed"
    assert final["score"] == 88
    assert final["attempts"] == 2


def test_image_upload_enters_the_diagnostic_message() -> None:
    client, model = make_client()

    response = client.post(
        "/api/sessions",
        data={"topic": "解释流程图"},
        files={"image": ("graph.png", b"png-bytes", "image/png")},
    )

    assert response.status_code == 201
    content = model.diagnostic_messages[1].content
    assert content[1]["type"] == "image"
    assert content[1]["mime_type"] == "image/png"


def test_web_rejects_empty_input_and_unknown_session() -> None:
    client, _ = make_client()

    empty = client.post("/api/sessions", data={"topic": "  "})
    missing = client.post(
        "/api/sessions/missing/answers", json={"answer": "回答"}
    )

    assert empty.status_code == 422
    assert missing.status_code == 404


def test_config_endpoint_never_exposes_credentials() -> None:
    client, _ = make_client()

    response = client.get("/api/config")

    assert response.json() == {
        "configured": True,
        "chat_model_id": "fake:coach",
        "assessment_model_id": "fake:assessment",
        "embedding_model_id": "local:hash-v1",
        "accepts_images": True,
        "run_timeout_seconds": 120.0,
        "context_model_call_limit": 3,
        "context_tool_call_limit": 2,
    }
    assert "api_key" not in response.text.lower()


def test_config_endpoint_exposes_fallback_ids_without_credentials() -> None:
    model = FakeChatModel()
    models = LearningCoachModels.from_models(
        model,
        chat_fallback_model=model,
        assessment_fallback_model=model,
    )
    service = LearningSessionService(
        models=models,
        chat_model_id="fake:coach",
        assessment_model_id="fake:assessment",
        chat_fallback_model_id="fake:coach-fallback",
        assessment_fallback_model_id="fake:assessment-fallback",
    )
    client = TestClient(create_app(service=service))

    response = client.get("/api/config")

    assert response.json() == {
        "configured": True,
        "chat_model_id": "fake:coach",
        "assessment_model_id": "fake:assessment",
        "chat_fallback_model_id": "fake:coach-fallback",
        "assessment_fallback_model_id": "fake:assessment-fallback",
        "embedding_model_id": "local:hash-v1",
        "accepts_images": True,
        "run_timeout_seconds": 120.0,
        "context_model_call_limit": 3,
        "context_tool_call_limit": 2,
    }
    assert "api_key" not in response.text.lower()


def test_config_endpoint_reports_invalid_model_settings() -> None:
    def invalid_models() -> LearningCoachModels:
        raise ValueError("未知模型供应商")

    service = LearningSessionService(models_factory=invalid_models)
    client = TestClient(create_app(service=service))

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "error": "未知模型供应商",
    }


def test_web_timeout_setting_accepts_only_positive_numbers() -> None:
    assert web_run_timeout_seconds({}) == 120
    assert web_run_timeout_seconds({"WEB_RUN_TIMEOUT_SECONDS": "45.5"}) == 45.5

    with pytest.raises(RuntimeError, match="必须是正数"):
        web_run_timeout_seconds({"WEB_RUN_TIMEOUT_SECONDS": "0"})
    with pytest.raises(RuntimeError, match="必须是正数"):
        web_run_timeout_seconds({"WEB_RUN_TIMEOUT_SECONDS": "secret"})


def test_web_graph_config_contains_safe_session_metadata_only() -> None:
    config = session_run_config("random-session", has_study_material=True)
    assert config["run_name"] == "learning_coach_session"
    assert config["tags"] == ["learning-coach", "surface:web"]
    assert config["metadata"]["component"] == "learning-coach"
    assert config["metadata"]["surface"] == "web"
    assert config["metadata"]["has_study_material"] is True
    assert config["metadata"]["session_id"] == "random-session"
    serialized = str(config)
    assert "敏感主题" not in serialized
    assert "私人资料正文" not in serialized


def _sse_events(response: Any) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = "message"
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append(
                (event_name, json.loads(line.removeprefix("data: ")))
            )
    return events


def test_stream_endpoints_emit_ordered_sse_events_and_final_state() -> None:
    client, _ = make_client()

    started = client.post(
        "/api/sessions/stream",
        data={
            "topic": "LangGraph 条件边",
            "study_material": "State 是 LangGraph 条件边 的前置知识。",
        },
    )

    assert started.status_code == 201
    assert started.headers["content-type"].startswith("text/event-stream")
    start_events = _sse_events(started)
    assert start_events[-1][0] == "done"
    state = next(payload for event, payload in start_events if event == "state")
    assert state["stage"] == "diagnostic"

    answered = client.post(
        f"/api/sessions/{state['session_id']}/answers/stream",
        json={"answer": "它读取状态后选择下一节点。"},
    )
    answer_events = _sse_events(answered)
    event_names = [event for event, _ in answer_events]

    assert answered.status_code == 200
    assert "status" in event_names
    assert "token" in event_names
    assert "sources" in event_names
    assert "retrieval" in event_names
    assert "knowledge_graph" in event_names
    assert event_names[-2:] == ["state", "done"]
    teaching_text = "".join(
        payload["text"]
        for event, payload in answer_events
        if event == "token" and payload["task"] == "teaching"
    )
    final_state = next(
        payload for event, payload in answer_events if event == "state"
    )
    assert teaching_text == final_state["explanation"]
    assert final_state["sources"]
    retrieval_event = next(
        payload for event, payload in answer_events if event == "retrieval"
    )
    assert final_state["retrieval_report"] == retrieval_event["report"]
    graph_event = next(
        payload for event, payload in answer_events if event == "knowledge_graph"
    )
    assert final_state["graph_report"] == graph_event["report"]
    assert final_state["graph_report"]["graph_used"] is True
    assert "vector" not in json.dumps(final_state["graph_report"])


class SlowChatModel(FakeChatModel):
    def invoke(self, messages: Any) -> AIMessage:
        time.sleep(0.05)
        return super().invoke(messages)

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        structured = super().with_structured_output(schema, method=method)
        original_invoke = structured.invoke

        def slow_invoke(messages: Any) -> Diagnostic | Assessment:
            time.sleep(0.05)
            return original_invoke(messages)

        structured.invoke = slow_invoke  # type: ignore[method-assign]
        return structured


def test_stream_timeout_returns_safe_error_and_done_event() -> None:
    model = SlowChatModel()
    service = LearningSessionService(
        models=LearningCoachModels.from_models(model),
        chat_model_id="fake:slow",
        assessment_model_id="fake:slow",
        run_timeout_seconds=0.01,
    )
    client = TestClient(create_app(service=service))

    response = client.post(
        "/api/sessions/stream", data={"topic": "超时测试"}
    )
    events = _sse_events(response)

    assert response.status_code == 201
    assert events[-2] == (
        "error",
        {"code": "run_timeout", "message": "本次模型运行超时，请重试。"},
    )
    assert events[-1] == ("done", {"ok": False})
    assert "超时测试" not in events[-2][1]["message"]


def test_home_page_exposes_study_material_streaming_and_cancel_controls() -> None:
    client, _ = make_client()

    response = client.get("/")

    assert 'id="study-material"' in response.text
    assert 'id="materials"' in response.text
    assert 'name="materials"' in response.text
    assert "multiple" in response.text
    assert 'id="source-urls"' in response.text
    assert 'id="context-ingestion"' in response.text
    assert 'id="context-retrieval"' in response.text
    assert 'id="concept-graph-card"' in response.text
    assert 'id="concept-graph-nodes"' in response.text
    assert 'id="prerequisite-list"' in response.text
    assert 'id="code-practice-card"' in response.text
    assert 'id="code-test-results"' in response.text
    assert 'id="code-hints"' in response.text
    assert 'id="learning-goal"' in response.text
    assert 'id="context-insight"' in response.text
    assert 'id="cancel-run"' in response.text
    app_script = client.get("/static/app.js").text
    assert "AbortController" in app_script
    assert "/api/sessions/stream" in app_script
    assert "answers/stream" in app_script
    assert 'stage === "teaching"' in app_script
    assert 'formData.append("learning_goal"' in app_script
    assert 'formData.append("materials"' in app_script
    assert 'formData.append("source_urls"' in app_script
    assert "source.source_name" in app_script
    assert "source.location" in app_script
    assert "ingestion_report" in app_script
    assert "context_summary" in app_script
    assert "context_report" in app_script
    assert "retrieval_report" in app_script
    assert "graph_report" in app_script
    assert 'eventName === "retrieval"' in app_script
    assert 'eventName === "knowledge_graph"' in app_script
    assert 'eventName === "code_practice"' in app_script
    assert "renderCodePractice" in app_script
    assert "renderKnowledgeGraph" in app_script
    assert "document.createElement" in app_script
    assert "retrieval_score?.rerank" in app_script
    assert "config.embedding_model_id" in app_script


def test_cancelled_stream_does_not_register_an_incomplete_session() -> None:
    model = SlowChatModel()
    service = LearningSessionService(
        models=LearningCoachModels.from_models(model),
        chat_model_id="fake:slow",
        assessment_model_id="fake:slow",
        run_timeout_seconds=1,
    )

    async def cancel_run() -> None:
        started = asyncio.Event()

        async def consume() -> None:
            async for _event in service.create_session_events("取消测试"):
                started.set()

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_run())
    assert service._sessions == set()


def test_web_history_and_fork_endpoints_support_time_travel() -> None:
    client, _ = make_client()

    started = client.post(
        "/api/sessions", data={"topic": "LangGraph 分叉"}
    ).json()
    client.post(
        f"/api/sessions/{started['session_id']}/answers",
        json={"answer": "检查点按步保存。"},
    )

    history = client.get(f"/api/sessions/{started['session_id']}/history")
    assert history.status_code == 200
    milestones = history.json()
    assert any(item["node"] == "collect_quiz" for item in milestones)
    assert all("explanation" not in item and "quiz_answer" not in item for item in milestones)

    quiz_checkpoint = next(
        item
        for item in milestones
        if item["node"] == "collect_quiz" and item["forkable"]
    )
    forked = client.post(
        f"/api/sessions/{started['session_id']}/fork",
        json={"checkpoint_id": quiz_checkpoint["checkpoint_id"]},
    )
    assert forked.status_code == 200
    payload = forked.json()
    assert payload["forked_from"] == started["session_id"]
    assert payload["entry_node"] == "collect_quiz"
    assert payload["session"]["status"] == "waiting"
    assert payload["session"]["stage"] == "quiz"

    missing = client.post(
        f"/api/sessions/{started['session_id']}/fork",
        json={"checkpoint_id": "missing"},
    )
    assert missing.status_code == 404


def test_web_long_term_memory_persists_across_sessions() -> None:
    client, _ = make_client()

    first = client.post(
        "/api/sessions",
        data={"topic": "LangGraph 记忆", "learner_id": "ray"},
    ).json()
    assert first["learner_id"] == "ray"
    assert first["long_term_memory"] is None
    client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "检查点保存每一步。"},
    )
    client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "thread_id 恢复会话。"},
    )

    second = client.post(
        "/api/sessions",
        data={"topic": "LangGraph 记忆进阶", "learner_id": "ray"},
    ).json()
    assert second["long_term_memory"]["sessions"] == 1
    assert second["long_term_memory"]["last_topic"] == "LangGraph 记忆"
