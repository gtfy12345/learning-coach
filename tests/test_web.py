from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from learning_coach.model import LearningCoachModels
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.web import LearningSessionService, create_app


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

    def invoke(self, messages: Any) -> AIMessage:
        return AIMessage(content=next(self.responses))

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        return FakeStructuredModel(self, schema)


def make_client(
    *, scores: tuple[int, ...] = (86,)
) -> tuple[TestClient, FakeChatModel]:
    model = FakeChatModel(scores)
    models = LearningCoachModels.from_models(model)
    service = LearningSessionService(
        models=models,
        chat_model_id="fake:coach",
        assessment_model_id="fake:assessment",
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

    diagnostic = client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "它根据状态选择节点。"},
    )
    assert diagnostic.status_code == 200
    second = diagnostic.json()
    assert second["stage"] == "quiz"
    assert second["explanation"] == "条件边根据状态选择下一节点。"
    assert "route_after_assessment" in second["question"]

    quiz = client.post(
        f"/api/sessions/{first['session_id']}/answers",
        json={"answer": "返回 retry 或 finish。"},
    )
    assert quiz.status_code == 200
    final = quiz.json()
    assert final["status"] == "completed"
    assert final["stage"] == "summary"
    assert final["score"] == 86
    assert "下一步" in final["summary"]


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
        "accepts_images": True,
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
        "accepts_images": True,
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
