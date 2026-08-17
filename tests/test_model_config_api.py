from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from learning_coach.model_config import RuntimeModelConfigService
from learning_coach.web import LearningSessionService, create_app


SECRET = "sk-api-route-secret"


def make_settings_client(
    *, client_host: str = "127.0.0.1"
) -> tuple[TestClient, list[tuple[str, str]], list[dict[str, str]]]:
    auth_calls: list[tuple[str, str]] = []
    secret_calls: list[dict[str, str]] = []

    def models_builder(settings: Any, api_keys: dict[str, str]) -> Any:
        secret_calls.append(dict(api_keys))
        return SimpleNamespace(name=settings.chat_model_id, accepts_images=False)

    config = RuntimeModelConfigService(
        models_builder=models_builder,
        runtime_builder=lambda models: SimpleNamespace(model_name=models.name),
        validator=lambda models: None,
    )
    initial_models = SimpleNamespace(name="initial", accepts_images=False)
    config.install_initial(
        models=initial_models,
        runtime=SimpleNamespace(model_name="initial"),
        chat_model_id="codex_cli:default",
        assessment_model_id="codex_cli:default",
        auth_mode="cli",
    )
    service = LearningSessionService(
        runtime_config_service=config,
        auth_action=lambda provider, action: auth_calls.append((provider, action)) or 0,
    )
    client = TestClient(
        create_app(service=service),
        base_url="http://127.0.0.1",
        client=(client_host, 50000),
    )
    return client, auth_calls, secret_calls


def same_origin_headers() -> dict[str, str]:
    return {"Origin": "http://127.0.0.1"}


def test_model_config_api_tests_then_applies_without_echoing_secrets() -> None:
    client, _auth_calls, secret_calls = make_settings_client()

    current = client.get("/api/model-config")
    tested = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "openai:gpt-5-mini",
            "assessment_model_id": "anthropic:claude-sonnet-4-6",
            "api_keys": {
                "openai": SECRET,
                "anthropic": "anthropic-secret",
            },
        },
    )
    applied = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={"auth_mode": "api", "test_id": tested.json()["test_id"]},
    )

    assert current.status_code == 200
    assert current.json()["version"] == 1
    assert tested.status_code == 200
    assert applied.status_code == 200
    assert applied.json()["version"] == 2
    assert applied.json()["chat_model_id"] == "openai:gpt-5-mini"
    assert secret_calls[0]["openai"] == SECRET
    assert SECRET not in current.text + tested.text + applied.text

    reused = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={"auth_mode": "api", "test_id": tested.json()["test_id"]},
    )
    assert reused.status_code == 422


def test_invalid_model_config_request_does_not_echo_api_key() -> None:
    client, _auth_calls, _secret_calls = make_settings_client()

    response = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "not-a-model-id",
            "api_keys": {"openai": SECRET},
        },
    )

    assert response.status_code == 422
    assert SECRET not in response.text


def test_settings_api_can_bootstrap_from_an_unconfigured_service() -> None:
    secret_calls: list[dict[str, str]] = []

    def models_builder(settings: Any, api_keys: dict[str, str]) -> Any:
        secret_calls.append(dict(api_keys))
        return SimpleNamespace(name=settings.chat_model_id, accepts_images=False)

    config = RuntimeModelConfigService(
        models_builder=models_builder,
        runtime_builder=lambda models: SimpleNamespace(model_name=models.name),
        validator=lambda models: None,
    )
    service = LearningSessionService(
        models_factory=lambda: (_ for _ in ()).throw(RuntimeError("没有启动模型")),
        runtime_config_service=config,
    )
    client = TestClient(
        create_app(service=service),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    initial = client.get("/api/model-config")
    tested = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "openai:gpt-5-mini",
            "api_keys": {"openai": SECRET},
        },
    )
    applied = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={"auth_mode": "api", "test_id": tested.json()["test_id"]},
    )
    home_config = client.get("/api/config")

    assert initial.status_code == 200
    assert initial.json()["configured"] is False
    assert tested.status_code == 200
    assert applied.status_code == 200
    assert applied.json()["configured"] is True
    assert home_config.status_code == 200
    assert home_config.json()["configured"] is True
    assert home_config.json()["chat_model_id"] == "openai:gpt-5-mini"
    assert secret_calls[0]["openai"] == SECRET
    assert SECRET not in initial.text + tested.text + applied.text


def test_cli_model_config_can_be_selected_without_api_test_id() -> None:
    client, _auth_calls, secret_calls = make_settings_client()

    response = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={
            "auth_mode": "cli",
            "chat_model_id": "claude_code:default",
            "assessment_model_id": "claude_code:default",
        },
    )

    assert response.status_code == 200
    assert response.json()["auth_mode"] == "cli"
    assert response.json()["chat_provider"] == "claude_code"
    assert secret_calls[-1] == {}


def test_sensitive_model_routes_reject_non_loopback_clients() -> None:
    client, auth_calls, secret_calls = make_settings_client(
        client_host="192.168.1.30"
    )

    config_response = client.get("/api/model-config")
    auth_response = client.get("/api/model-auth/codex/status")

    assert config_response.status_code == 403
    assert auth_response.status_code == 403
    assert auth_calls == []
    assert secret_calls == []


def test_sensitive_writes_require_same_origin_json() -> None:
    client, auth_calls, secret_calls = make_settings_client()

    cross_origin = client.post(
        "/api/model-config/test",
        headers={"Origin": "https://evil.example"},
        json={
            "chat_model_id": "openai:gpt-5-mini",
            "api_keys": {"openai": SECRET},
        },
    )
    form_write = client.post(
        "/api/model-auth/codex/login",
        headers=same_origin_headers(),
        data={},
    )

    assert cross_origin.status_code == 403
    assert form_write.status_code == 403
    assert auth_calls == []
    assert secret_calls == []


def test_auth_api_delegates_codex_and_claude_actions() -> None:
    client, auth_calls, _secret_calls = make_settings_client()

    status = client.get("/api/model-auth/codex/status")
    login = client.post(
        "/api/model-auth/claude/login",
        headers=same_origin_headers(),
        json={},
    )
    logout = client.post(
        "/api/model-auth/codex/logout",
        headers=same_origin_headers(),
        json={},
    )

    assert status.json() == {"provider": "codex", "action": "status", "ok": True}
    assert login.json() == {"provider": "claude", "action": "login", "ok": True}
    assert logout.json() == {"provider": "codex", "action": "logout", "ok": True}
    assert auth_calls == [
        ("codex", "status"),
        ("claude", "login"),
        ("codex", "logout"),
    ]
