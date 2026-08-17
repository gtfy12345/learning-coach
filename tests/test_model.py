from typing import Any

import pytest

from learning_coach.model import (
    LearningCoachModels,
    ModelCapabilities,
    ModelSettings,
    _create_chat_model,
    create_chat_model,
    create_model_suite,
    image_inputs_enabled,
    select_structured_output_method,
)


class FakeModel:
    def __init__(self, profile: dict[str, bool] | None = None) -> None:
        self.profile = profile
        self.structured_calls: list[tuple[type[Any], str]] = []

    def with_structured_output(self, schema: type[Any], *, method: str) -> object:
        self.structured_calls.append((schema, method))
        return object()


def capabilities(**values: bool | None) -> ModelCapabilities:
    return ModelCapabilities(
        native_structured_output=values.get("native_structured_output"),
        tool_calling=values.get("tool_calling"),
        image_inputs=values.get("image_inputs"),
        prompt_structured_output=values.get("prompt_structured_output"),
    )


def test_settings_support_separate_chat_and_assessment_models() -> None:
    settings = ModelSettings.from_environ(
        {
            "CHAT_MODEL_ID": "openai:gpt-5-mini",
            "ASSESSMENT_MODEL_ID": "anthropic:claude-sonnet-4-6",
            "STRUCTURED_OUTPUT_STRATEGY": "tool",
            "IMAGE_INPUT_POLICY": "allow",
        }
    )

    assert settings.chat_model_id == "openai:gpt-5-mini"
    assert settings.assessment_model_id == "anthropic:claude-sonnet-4-6"
    assert settings.structured_output_strategy == "tool"
    assert settings.image_input_policy == "allow"


def test_settings_support_optional_advanced_teaching_model() -> None:
    configured = ModelSettings.from_environ(
        {
            "CHAT_MODEL_ID": "openai:gpt-5-mini",
            "ADVANCED_CHAT_MODEL_ID": "openai:gpt-5.4",
        }
    )
    defaulted = ModelSettings.from_environ(
        {"CHAT_MODEL_ID": "openai:gpt-5-mini"}
    )

    assert configured.advanced_chat_model_id == "openai:gpt-5.4"
    assert defaulted.advanced_chat_model_id is None


def test_settings_support_fallback_inheritance_and_role_override() -> None:
    inherited = ModelSettings.from_environ(
        {
            "CHAT_MODEL_ID": "openai:gpt-5-mini",
            "CHAT_FALLBACK_MODEL_ID": "anthropic:claude-sonnet-4-6",
        }
    )
    overridden = ModelSettings.from_environ(
        {
            "CHAT_MODEL_ID": "openai:gpt-5-mini",
            "CHAT_FALLBACK_MODEL_ID": "anthropic:claude-sonnet-4-6",
            "ASSESSMENT_FALLBACK_MODEL_ID": "google_genai:gemini-2.5-flash-lite",
        }
    )

    assert inherited.chat_fallback_model_id == "anthropic:claude-sonnet-4-6"
    assert inherited.assessment_fallback_model_id == "anthropic:claude-sonnet-4-6"
    assert overridden.assessment_fallback_model_id == (
        "google_genai:gemini-2.5-flash-lite"
    )


def test_settings_leave_fallbacks_disabled_by_default() -> None:
    settings = ModelSettings.from_environ(
        {"CHAT_MODEL_ID": "openai:gpt-5-mini"}
    )

    assert settings.chat_fallback_model_id is None
    assert settings.assessment_fallback_model_id is None


def test_settings_keep_legacy_model_id_compatible() -> None:
    settings = ModelSettings.from_environ({"MODEL_ID": "openai:gpt-5-mini"})

    assert settings.chat_model_id == "openai:gpt-5-mini"
    assert settings.assessment_model_id == "openai:gpt-5-mini"


def test_settings_validate_cli_timeout() -> None:
    with pytest.raises(RuntimeError, match="CLI_MODEL_TIMEOUT_SECONDS"):
        ModelSettings.from_environ(
            {
                "CHAT_MODEL_ID": "codex_cli:default",
                "CLI_MODEL_TIMEOUT_SECONDS": "0",
            }
        )


def test_openai_compatible_endpoint_uses_configured_base_url(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_MODEL_ID", "openai:compatible-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")

    model = create_chat_model()

    assert str(model.root_client.base_url) == "https://example.com/v1/"


def test_domestic_provider_uses_openai_driver_with_logical_credentials(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    sentinel = object()

    def fake_init(model: str, **kwargs: Any) -> object:
        calls.append((model, kwargs))
        return sentinel

    monkeypatch.setattr("learning_coach.model.init_chat_model", fake_init)

    model = _create_chat_model(
        "deepseek:deepseek-v4-flash",
        api_keys={"deepseek": "deepseek-secret"},
        api_base_urls={"deepseek": "https://api.deepseek.com"},
    )

    assert model is sentinel
    assert calls == [
        (
            "deepseek-v4-flash",
            {
                "model_provider": "openai",
                "temperature": 0,
                "api_key": "deepseek-secret",
                "base_url": "https://api.deepseek.com",
            },
        )
    ]


def test_existing_provider_keeps_native_model_initialization(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(
        "learning_coach.model.init_chat_model",
        lambda model, **kwargs: calls.append((model, kwargs)) or object(),
    )

    _create_chat_model(
        "anthropic:claude-sonnet-4-6",
        api_keys={"anthropic": "anthropic-secret"},
        api_base_urls={"anthropic": "https://ignored.example.com"},
    )

    assert calls == [
        (
            "anthropic:claude-sonnet-4-6",
            {"temperature": 0, "api_key": "anthropic-secret"},
        )
    ]


def test_auto_prefers_native_structured_output() -> None:
    method = select_structured_output_method(
        capabilities(native_structured_output=True, tool_calling=True), "auto"
    )

    assert method == "json_schema"


def test_auto_falls_back_to_tool_strategy() -> None:
    method = select_structured_output_method(
        capabilities(native_structured_output=False, tool_calling=True), "auto"
    )

    assert method == "function_calling"


def test_unknown_profile_uses_portable_tool_strategy() -> None:
    assert (
        select_structured_output_method(capabilities(), "auto")
        == "function_calling"
    )


def test_cli_model_can_use_validated_prompt_json_as_last_resort() -> None:
    assert (
        select_structured_output_method(
            capabilities(
                native_structured_output=False,
                tool_calling=False,
                prompt_structured_output=True,
            ),
            "auto",
        )
        == "prompt_json"
    )


def test_explicit_unsupported_strategy_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="不支持原生"):
        select_structured_output_method(
            capabilities(native_structured_output=False), "native"
        )


def test_model_suite_negotiates_each_role_independently() -> None:
    chat = FakeModel(
        {"structured_output": False, "tool_calling": True, "image_inputs": True}
    )
    assessment = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": False}
    )

    suite = LearningCoachModels.from_models(chat, assessment)

    assert suite.diagnostic_method == "function_calling"
    assert suite.assessment_method == "json_schema"
    assert suite.accepts_images is True
    assert chat.structured_calls[0][1] == "function_calling"
    assert assessment.structured_calls[0][1] == "json_schema"


def test_model_suite_carries_optional_advanced_teaching_model() -> None:
    chat = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": True}
    )
    advanced = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": True}
    )

    suite = LearningCoachModels.from_models(
        chat, advanced_chat_model=advanced
    )

    assert suite.advanced_chat is advanced


def test_model_suite_negotiates_fallback_roles_independently() -> None:
    chat = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": True}
    )
    assessment = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": False}
    )
    chat_fallback = FakeModel(
        {"structured_output": False, "tool_calling": True, "image_inputs": True}
    )
    assessment_fallback = FakeModel(
        {"structured_output": True, "tool_calling": True, "image_inputs": False}
    )

    suite = LearningCoachModels.from_models(
        chat,
        assessment,
        chat_fallback_model=chat_fallback,
        assessment_fallback_model=assessment_fallback,
    )

    assert suite.chat_fallback is chat_fallback
    assert suite.diagnostic_fallback_method == "function_calling"
    assert suite.assessment_fallback_method == "json_schema"
    assert chat_fallback.structured_calls[0][1] == "function_calling"
    assert assessment_fallback.structured_calls[0][1] == "json_schema"


def test_create_model_suite_reuses_matching_fallback_model_id(monkeypatch) -> None:
    created: list[str] = []

    def fake_create(model_id: str, *, cli_timeout_seconds: int = 300) -> FakeModel:
        created.append(model_id)
        return FakeModel(
            {
                "structured_output": True,
                "tool_calling": True,
                "image_inputs": True,
            }
        )

    monkeypatch.setenv("CHAT_MODEL_ID", "openai:primary")
    monkeypatch.setenv("ASSESSMENT_MODEL_ID", "openai:primary")
    monkeypatch.setenv("CHAT_FALLBACK_MODEL_ID", "anthropic:fallback")
    monkeypatch.delenv("ASSESSMENT_FALLBACK_MODEL_ID", raising=False)
    monkeypatch.setattr("learning_coach.model._create_chat_model", fake_create)

    suite = create_model_suite()

    assert created == ["openai:primary", "anthropic:fallback"]
    assert suite.chat_fallback is not None
    assert suite.assessment_fallback is not None


def test_image_policy_requires_profile_support_unless_overridden() -> None:
    unknown = capabilities(image_inputs=None)

    assert image_inputs_enabled(unknown, "auto") is False
    assert image_inputs_enabled(unknown, "allow") is True
    assert image_inputs_enabled(capabilities(image_inputs=True), "deny") is False
