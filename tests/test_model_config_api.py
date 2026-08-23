from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from learning_coach.model_config import RuntimeModelConfigService
from learning_coach.web import LearningSessionService, create_app


SECRET = "sk-api-route-secret"


def make_settings_client(
    *, client_host: str = "127.0.0.1", env_file: Any | None = None
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
    service_kwargs: dict[str, Any] = {
        "runtime_config_service": config,
        "auth_action": lambda provider, action: auth_calls.append(
            (provider, action)
        )
        or 0,
    }
    if env_file is not None:
        service_kwargs["env_file"] = env_file
    service = LearningSessionService(**service_kwargs)
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


def test_domestic_model_config_keeps_logical_provider_and_hides_connection_input() -> None:
    client, _auth_calls, secret_calls = make_settings_client()
    secret = "deepseek-private-secret"
    base_url = "https://gateway.example.com/deepseek"

    tested = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "deepseek:deepseek-v4-flash",
            "assessment_model_id": "zhipu:glm-5-turbo",
            "api_keys": {
                "deepseek": secret,
                "zhipu": "zhipu-private-secret",
            },
            "base_urls": {"deepseek": base_url},
        },
    )

    assert tested.status_code == 200
    assert tested.json()["config"]["chat_provider"] == "deepseek"
    assert tested.json()["config"]["assessment_provider"] == "zhipu"
    assert secret_calls[-1]["deepseek"] == secret
    assert secret not in tested.text
    assert base_url not in tested.text
    assert "base_urls" not in tested.text


def test_custom_compatible_api_rejects_unsafe_endpoint_without_echoing_secret() -> None:
    client, _auth_calls, secret_calls = make_settings_client()
    secret = "custom-private-secret"

    response = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "openai_compatible:custom-model",
            "api_keys": {"openai_compatible": secret},
            "base_urls": {
                "openai_compatible": "http://127.0.0.1:9000/v1?token=visible"
            },
        },
    )

    assert response.status_code == 422
    assert secret_calls == []
    assert secret not in response.text


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


def test_apply_with_persist_to_env_writes_local_env_file(tmp_path) -> None:
    from dotenv import dotenv_values

    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHECKPOINT_DB_PATH=data/checkpoints.db\n", encoding="utf-8"
    )
    client, _auth_calls, _secret_calls = make_settings_client(env_file=env_file)
    secret = "zhipu-private-secret"

    tested = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "zhipu:glm-5.3",
            "assessment_model_id": "zhipu:glm-5.3",
            "api_keys": {"zhipu": secret},
            "base_urls": {
                "zhipu": "https://open.bigmodel.cn/api/coding/paas/v4"
            },
        },
    )
    assert tested.status_code == 200

    before = client.get("/api/model-config")
    assert before.json()["configured"] is True
    assert before.json()["env_model_configured"] is False

    applied = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={
            "auth_mode": "api",
            "test_id": tested.json()["test_id"],
            "persist_to_env": True,
        },
    )
    assert applied.status_code == 200
    body = applied.json()
    assert set(body["env_keys_written"]) == {
        "CHAT_MODEL_ID",
        "ASSESSMENT_MODEL_ID",
        "ZHIPU_API_KEY",
        "ZHIPU_BASE_URL",
    }
    assert secret not in applied.text

    values = dotenv_values(env_file)
    assert values["CHAT_MODEL_ID"] == "zhipu:glm-5.3"
    assert values["ASSESSMENT_MODEL_ID"] == "zhipu:glm-5.3"
    assert values["ZHIPU_API_KEY"] == secret
    assert values["ZHIPU_BASE_URL"] == "https://open.bigmodel.cn/api/coding/paas/v4"
    assert values["CHECKPOINT_DB_PATH"] == "data/checkpoints.db"
    assert env_file.stat().st_mode & 0o777 == 0o600

    after = client.get("/api/model-config")
    assert after.json()["env_model_configured"] is True


def test_apply_without_persist_flag_leaves_env_file_untouched(tmp_path) -> None:
    from dotenv import dotenv_values

    env_file = tmp_path / ".env"
    client, _auth_calls, _secret_calls = make_settings_client(env_file=env_file)

    tested = client.post(
        "/api/model-config/test",
        headers=same_origin_headers(),
        json={
            "chat_model_id": "deepseek:deepseek-v4-flash",
            "assessment_model_id": "deepseek:deepseek-v4-flash",
            "api_keys": {"deepseek": "deepseek-secret"},
        },
    )
    assert tested.status_code == 200

    applied = client.put(
        "/api/model-config",
        headers=same_origin_headers(),
        json={
            "auth_mode": "api",
            "test_id": tested.json()["test_id"],
            "persist_to_env": False,
        },
    )
    assert applied.status_code == 200
    assert applied.json()["env_keys_written"] == []
    assert not env_file.exists() or not dotenv_values(env_file).get(
        "DEEPSEEK_API_KEY"
    )
