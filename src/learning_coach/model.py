import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

from learning_coach.cli_models import create_cli_chat_model, is_cli_model_id
from learning_coach.schemas import Assessment, Diagnostic

StructuredOutputStrategy = Literal["auto", "native", "tool"]
StructuredOutputMethod = Literal["json_schema", "function_calling", "prompt_json"]
ImageInputPolicy = Literal["auto", "allow", "deny"]

OPENAI_COMPATIBLE_PROVIDER_DEFAULTS: dict[str, str | None] = {
    "deepseek": "https://api.deepseek.com",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "openai_compatible": None,
}


def _choice(value: str, *, name: str, allowed: tuple[str, ...]) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        choices = ", ".join(allowed)
        raise RuntimeError(f"{name} 必须是以下值之一：{choices}。")
    return normalized


@dataclass(frozen=True)
class ModelSettings:
    """Environment-backed model choices for teaching and assessment roles."""

    chat_model_id: str
    assessment_model_id: str
    advanced_chat_model_id: str | None = None
    chat_fallback_model_id: str | None = None
    assessment_fallback_model_id: str | None = None
    structured_output_strategy: StructuredOutputStrategy = "auto"
    image_input_policy: ImageInputPolicy = "auto"
    cli_timeout_seconds: int = 300
    api_base_urls: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "ModelSettings":
        legacy_model_id = environ.get("MODEL_ID", "").strip()
        chat_model_id = environ.get("CHAT_MODEL_ID", "").strip() or legacy_model_id
        if not chat_model_id:
            raise RuntimeError(
                "没有找到 CHAT_MODEL_ID 或 MODEL_ID。"
                "请用 --model 启动 Web、访问本机 /settings，"
                "或设置对应环境变量。"
            )

        assessment_model_id = environ.get(
            "ASSESSMENT_MODEL_ID", chat_model_id
        ).strip()
        if not assessment_model_id:
            assessment_model_id = chat_model_id

        chat_fallback_model_id = (
            environ.get("CHAT_FALLBACK_MODEL_ID", "").strip() or None
        )
        advanced_chat_model_id = (
            environ.get("ADVANCED_CHAT_MODEL_ID", "").strip() or None
        )
        assessment_fallback_model_id = (
            environ.get("ASSESSMENT_FALLBACK_MODEL_ID", "").strip()
            or chat_fallback_model_id
        )

        strategy = _choice(
            environ.get("STRUCTURED_OUTPUT_STRATEGY", "auto"),
            name="STRUCTURED_OUTPUT_STRATEGY",
            allowed=("auto", "native", "tool"),
        )
        image_policy = _choice(
            environ.get("IMAGE_INPUT_POLICY", "auto"),
            name="IMAGE_INPUT_POLICY",
            allowed=("auto", "allow", "deny"),
        )
        timeout_value = environ.get("CLI_MODEL_TIMEOUT_SECONDS", "300").strip()
        try:
            cli_timeout_seconds = int(timeout_value)
        except ValueError as exc:
            raise RuntimeError("CLI_MODEL_TIMEOUT_SECONDS 必须是正整数。") from exc
        if cli_timeout_seconds <= 0:
            raise RuntimeError("CLI_MODEL_TIMEOUT_SECONDS 必须是正整数。")
        return cls(
            chat_model_id=chat_model_id,
            assessment_model_id=assessment_model_id,
            advanced_chat_model_id=advanced_chat_model_id,
            chat_fallback_model_id=chat_fallback_model_id,
            assessment_fallback_model_id=assessment_fallback_model_id,
            structured_output_strategy=cast(StructuredOutputStrategy, strategy),
            image_input_policy=cast(ImageInputPolicy, image_policy),
            cli_timeout_seconds=cli_timeout_seconds,
        )


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities used by the app, projected from a LangChain model profile."""

    native_structured_output: bool | None
    tool_calling: bool | None
    image_inputs: bool | None
    prompt_structured_output: bool | None

    @classmethod
    def from_model(cls, model: Any) -> "ModelCapabilities":
        profile = getattr(model, "profile", None)
        if not isinstance(profile, Mapping):
            profile = {}
        return cls(
            native_structured_output=_optional_bool(
                profile.get("structured_output")
            ),
            tool_calling=_optional_bool(profile.get("tool_calling")),
            image_inputs=_optional_bool(profile.get("image_inputs")),
            prompt_structured_output=_optional_bool(
                profile.get("learning_coach_prompt_structured_output")
            ),
        )


def select_structured_output_method(
    capabilities: ModelCapabilities,
    strategy: StructuredOutputStrategy,
) -> StructuredOutputMethod:
    """Choose provider-native JSON Schema or the portable tool strategy."""

    if strategy == "native":
        if capabilities.native_structured_output is False:
            raise RuntimeError("当前模型明确不支持原生 Structured Output。")
        return "json_schema"

    if strategy == "tool":
        if capabilities.tool_calling is False:
            raise RuntimeError("当前模型明确不支持 Tool Strategy。")
        return "function_calling"

    if capabilities.native_structured_output is True:
        return "json_schema"
    if capabilities.tool_calling is not False:
        return "function_calling"
    if capabilities.prompt_structured_output is True:
        return "prompt_json"
    raise RuntimeError(
        "当前模型不支持原生 Structured Output、Tool Strategy 或受验证的 JSON 回退。"
    )


def image_inputs_enabled(
    capabilities: ModelCapabilities,
    policy: ImageInputPolicy,
) -> bool:
    """Gate image content using profile data unless the user explicitly overrides it."""

    if policy == "allow":
        return True
    if policy == "deny":
        return False
    return capabilities.image_inputs is True


def _with_structured_output(
    model: Any,
    schema: type[Any],
    strategy: StructuredOutputStrategy,
) -> tuple[Any, StructuredOutputMethod]:
    method = select_structured_output_method(
        ModelCapabilities.from_model(model), strategy
    )
    return model.with_structured_output(schema, method=method), method


@dataclass(frozen=True)
class LearningCoachModels:
    """Models and negotiated capabilities used by the learning workflow."""

    chat: Any
    diagnostic: Any
    assessment: Any
    chat_capabilities: ModelCapabilities
    diagnostic_method: StructuredOutputMethod
    assessment_method: StructuredOutputMethod
    accepts_images: bool
    advanced_chat: Any | None = None
    chat_fallback: Any | None = None
    diagnostic_fallback: Any | None = None
    assessment_fallback: Any | None = None
    diagnostic_fallback_method: StructuredOutputMethod | None = None
    assessment_fallback_method: StructuredOutputMethod | None = None

    @classmethod
    def from_models(
        cls,
        chat_model: Any,
        assessment_model: Any | None = None,
        *,
        advanced_chat_model: Any | None = None,
        chat_fallback_model: Any | None = None,
        assessment_fallback_model: Any | None = None,
        structured_output_strategy: StructuredOutputStrategy = "auto",
        image_input_policy: ImageInputPolicy = "auto",
    ) -> "LearningCoachModels":
        assessment_base = (
            assessment_model if assessment_model is not None else chat_model
        )
        diagnostic, diagnostic_method = _with_structured_output(
            chat_model, Diagnostic, structured_output_strategy
        )
        assessment, assessment_method = _with_structured_output(
            assessment_base, Assessment, structured_output_strategy
        )
        diagnostic_fallback = None
        diagnostic_fallback_method = None
        if chat_fallback_model is not None:
            diagnostic_fallback, diagnostic_fallback_method = _with_structured_output(
                chat_fallback_model, Diagnostic, structured_output_strategy
            )
        assessment_fallback = None
        assessment_fallback_method = None
        if assessment_fallback_model is not None:
            assessment_fallback, assessment_fallback_method = _with_structured_output(
                assessment_fallback_model, Assessment, structured_output_strategy
            )
        chat_capabilities = ModelCapabilities.from_model(chat_model)
        return cls(
            chat=chat_model,
            diagnostic=diagnostic,
            assessment=assessment,
            chat_capabilities=chat_capabilities,
            diagnostic_method=diagnostic_method,
            assessment_method=assessment_method,
            accepts_images=image_inputs_enabled(
                chat_capabilities, image_input_policy
            ),
            advanced_chat=advanced_chat_model,
            chat_fallback=chat_fallback_model,
            diagnostic_fallback=diagnostic_fallback,
            assessment_fallback=assessment_fallback,
            diagnostic_fallback_method=diagnostic_fallback_method,
            assessment_fallback_method=assessment_fallback_method,
        )


def _create_chat_model(
    model_id: str,
    *,
    cli_timeout_seconds: int = 300,
    api_keys: Mapping[str, str] | None = None,
    api_base_urls: Mapping[str, str] | None = None,
) -> Any:
    if is_cli_model_id(model_id):
        return create_cli_chat_model(
            model_id, timeout_seconds=cli_timeout_seconds
        )
    provider, _, model_name = model_id.partition(":")
    model_kwargs: dict[str, Any] = {"temperature": 0}
    target_model_id = model_id
    if provider in OPENAI_COMPATIBLE_PROVIDER_DEFAULTS:
        target_model_id = model_name
        model_kwargs["model_provider"] = "openai"
        base_url = (api_base_urls or {}).get(provider)
        if not base_url:
            base_url = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS[provider]
        if not base_url:
            raise RuntimeError(f"{provider} 缺少 Base URL。")
        model_kwargs["base_url"] = base_url
    api_key = (api_keys or {}).get(provider)
    if api_key:
        key_name = "google_api_key" if provider == "google_genai" else "api_key"
        model_kwargs[key_name] = api_key
    return init_chat_model(target_model_id, **model_kwargs)


def create_chat_model() -> Any:
    """Create the teaching model while preserving the first article's public API."""

    load_dotenv()
    settings = ModelSettings.from_environ(os.environ)
    return _create_chat_model(
        settings.chat_model_id,
        cli_timeout_seconds=settings.cli_timeout_seconds,
    )


def create_model_suite() -> LearningCoachModels:
    """Create role-specific models and negotiate their structured output methods."""

    load_dotenv()
    settings = ModelSettings.from_environ(os.environ)
    return create_model_suite_from_settings(settings)


def create_model_suite_from_settings(
    settings: ModelSettings,
    api_keys: Mapping[str, str] | None = None,
) -> LearningCoachModels:
    """Create a suite from explicit in-memory settings without mutating env."""

    models_by_id: dict[str, Any] = {}

    def model_for(model_id: str | None) -> Any | None:
        if model_id is None:
            return None
        if model_id not in models_by_id:
            kwargs: dict[str, Any] = {
                "cli_timeout_seconds": settings.cli_timeout_seconds
            }
            if api_keys is not None:
                kwargs["api_keys"] = api_keys
            if settings.api_base_urls:
                kwargs["api_base_urls"] = settings.api_base_urls
            models_by_id[model_id] = _create_chat_model(model_id, **kwargs)
        return models_by_id[model_id]

    chat_model = model_for(settings.chat_model_id)
    assessment_model = model_for(settings.assessment_model_id)
    advanced_chat_model = model_for(settings.advanced_chat_model_id)
    chat_fallback_model = model_for(settings.chat_fallback_model_id)
    assessment_fallback_model = model_for(settings.assessment_fallback_model_id)
    assert chat_model is not None
    assert assessment_model is not None
    return LearningCoachModels.from_models(
        chat_model,
        assessment_model,
        advanced_chat_model=advanced_chat_model,
        chat_fallback_model=chat_fallback_model,
        assessment_fallback_model=assessment_fallback_model,
        structured_output_strategy=settings.structured_output_strategy,
        image_input_policy=settings.image_input_policy,
    )
