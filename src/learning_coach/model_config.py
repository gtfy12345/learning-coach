from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator

from learning_coach.model import (
    LearningCoachModels,
    ModelSettings,
    OPENAI_COMPATIBLE_PROVIDER_DEFAULTS,
    build_env_export,
    create_model_suite_from_settings,
)
from learning_coach.schemas import Assessment, Diagnostic

ApiProvider = Literal[
    "openai",
    "anthropic",
    "google_genai",
    "deepseek",
    "dashscope",
    "zhipu",
    "openai_compatible",
]
CliProvider = Literal["codex_cli", "claude_code"]
AuthMode = Literal["api", "cli"]

API_PROVIDERS = frozenset(
    {"openai", "anthropic", "google_genai"}
    | OPENAI_COMPATIBLE_PROVIDER_DEFAULTS.keys()
)
CLI_PROVIDERS = frozenset({"codex_cli", "claude_code"})
DEFAULT_TEST_TTL = timedelta(minutes=5)
DEFAULT_MAX_CANDIDATES = 8


def _model_id(value: str) -> str:
    normalized = value.strip()
    provider, separator, name = normalized.partition(":")
    if not separator or not provider or not name:
        raise ValueError("模型 ID 必须使用 provider:model 格式。")
    return normalized


def model_provider(model_id: str) -> str:
    return _model_id(model_id).partition(":")[0]


def persist_env_file(path: Path, values: Mapping[str, str]) -> list[str]:
    """Write selected model config keys into the local .env file.

    Existing lines are preserved; only the supplied keys are updated. The
    file is created with owner-only permissions because it may hold API keys.
    """

    from dotenv import set_key

    if not values:
        return []
    written: list[str] = []
    for key in sorted(values):
        set_key(str(path), key, str(values[key]))
        written.append(key)
    try:
        path.touch(exist_ok=True)
        path.chmod(0o600)
    except OSError:
        pass
    return written


def env_file_has_model_config(path: Path) -> bool:
    """Whether the local .env already carries a startup model selection."""

    from dotenv import dotenv_values

    try:
        return bool(str(dotenv_values(path).get("CHAT_MODEL_ID", "")).strip())
    except OSError:
        return False


def _compatible_base_url(value: str, *, provider: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"{provider} Base URL 必须使用 HTTPS。")
    if not parsed.hostname:
        raise ValueError(f"{provider} Base URL 必须包含主机。")
    if parsed.username or parsed.password:
        raise ValueError(f"{provider} Base URL 不得包含用户凭据。")
    if parsed.query:
        raise ValueError(f"{provider} Base URL 不得包含查询参数。")
    if parsed.fragment:
        raise ValueError(f"{provider} Base URL 不得包含片段。")
    return normalized


def resolve_api_base_urls(
    providers: set[str], submitted: Mapping[str, str]
) -> dict[str, str]:
    """Resolve and validate endpoints only for selected compatible providers."""

    resolved: dict[str, str] = {}
    for provider in sorted(providers):
        if provider not in OPENAI_COMPATIBLE_PROVIDER_DEFAULTS:
            continue
        value = submitted.get(provider, "").strip()
        if not value:
            value = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS[provider] or ""
        if not value:
            raise ValueError(f"自定义兼容接口 {provider} 缺少 Base URL。")
        resolved[provider] = _compatible_base_url(value, provider=provider)
    return resolved


class ApiModelConfigInput(BaseModel):
    chat_model_id: str = Field(min_length=3, max_length=200)
    assessment_model_id: str | None = Field(default=None, max_length=200)
    api_keys: dict[str, SecretStr]
    base_urls: dict[str, str] = Field(default_factory=dict)

    @field_validator("chat_model_id")
    @classmethod
    def validate_chat_model_id(cls, value: str) -> str:
        return _model_id(value)

    @field_validator("assessment_model_id")
    @classmethod
    def validate_assessment_model_id(cls, value: str | None) -> str | None:
        return _model_id(value) if value is not None else None


class PublicRuntimeModelConfig(BaseModel):
    configured: Literal[True] = True
    auth_mode: AuthMode
    chat_model_id: str
    assessment_model_id: str
    chat_provider: str
    assessment_provider: str
    api_key_configured: dict[str, bool] = Field(default_factory=dict)
    version: int = Field(ge=1)
    env_model_configured: bool = False
    env_keys_written: list[str] = Field(default_factory=list)


class TestedRuntimeModelConfig(BaseModel):
    test_id: str
    expires_at: datetime
    config: PublicRuntimeModelConfig


@dataclass(frozen=True)
class RuntimeModelVersion:
    config: PublicRuntimeModelConfig
    models: LearningCoachModels | Any
    runtime: Any


@dataclass(frozen=True)
class _PendingCandidate:
    expires_at: datetime
    models: LearningCoachModels | Any
    runtime: Any
    config: PublicRuntimeModelConfig
    env_export: dict[str, str] = field(default_factory=dict)


def validate_model_suite(models: LearningCoachModels) -> None:
    """Make the smallest real calls that prove both structured roles work."""

    diagnostic = models.diagnostic.invoke(
        "为主题 1+1 生成一道最简诊断题，只返回契约要求的结构。"
    )
    assessment = models.assessment.invoke(
        "题目是 1+1，学习者回答 2。按契约评价该回答。"
    )
    if not isinstance(diagnostic, Diagnostic):
        Diagnostic.model_validate(diagnostic)
    if not isinstance(assessment, Assessment):
        Assessment.model_validate(assessment)


class RuntimeModelConfigService:
    """Hold tested model runtimes and secrets only in process memory."""

    def __init__(
        self,
        *,
        models_builder: Callable[
            [ModelSettings, Mapping[str, str]], LearningCoachModels | Any
        ] = create_model_suite_from_settings,
        runtime_builder: Callable[[LearningCoachModels | Any], Any] = lambda models: models,
        validator: Callable[[LearningCoachModels | Any], None] = validate_model_suite,
        now: Callable[[], datetime] | None = None,
        candidate_ttl: timedelta = DEFAULT_TEST_TTL,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> None:
        if candidate_ttl <= timedelta(0):
            raise ValueError("candidate_ttl 必须是正数。")
        if max_candidates <= 0:
            raise ValueError("max_candidates 必须是正整数。")
        self._models_builder = models_builder
        self._runtime_builder = runtime_builder
        self._validator = validator
        self._now = now or (lambda: datetime.now(UTC))
        self._candidate_ttl = candidate_ttl
        self._max_candidates = max_candidates
        self._current: RuntimeModelVersion | None = None
        self._pending: OrderedDict[str, _PendingCandidate] = OrderedDict()
        self._last_env_export: dict[str, str] = {}
        self._lock = threading.RLock()

    @property
    def pending_candidate_count(self) -> int:
        with self._lock:
            self._purge_expired()
            return len(self._pending)

    def install_initial(
        self,
        *,
        models: LearningCoachModels | Any,
        runtime: Any,
        chat_model_id: str,
        assessment_model_id: str,
        auth_mode: AuthMode,
    ) -> RuntimeModelVersion:
        with self._lock:
            if self._current is not None:
                return self._current
            config = self._public_config(
                auth_mode=auth_mode,
                chat_model_id=chat_model_id,
                assessment_model_id=assessment_model_id,
                api_key_configured={},
                version=1,
            )
            self._current = RuntimeModelVersion(config, models, runtime)
            return self._current

    def current(self) -> RuntimeModelVersion:
        with self._lock:
            if self._current is None:
                raise RuntimeError("模型运行时尚未初始化。")
            return self._current

    def test_api_config(
        self, request: ApiModelConfigInput
    ) -> TestedRuntimeModelConfig:
        chat_model_id = request.chat_model_id
        assessment_model_id = request.assessment_model_id or chat_model_id
        providers = {
            model_provider(chat_model_id),
            model_provider(assessment_model_id),
        }
        unsupported = providers - API_PROVIDERS
        if unsupported:
            raise ValueError(
                "API 配置不支持模型 Provider："
                + "、".join(sorted(unsupported))
                + "。"
            )
        api_keys = {
            provider: secret.get_secret_value().strip()
            for provider, secret in request.api_keys.items()
            if provider in API_PROVIDERS
        }
        missing = sorted(
            provider for provider in providers if not api_keys.get(provider)
        )
        if missing:
            raise ValueError("缺少 API Key：" + "、".join(missing) + "。")

        settings = ModelSettings(
            chat_model_id=chat_model_id,
            assessment_model_id=assessment_model_id,
            api_base_urls=resolve_api_base_urls(providers, request.base_urls),
        )
        try:
            models = self._models_builder(settings, api_keys)
            self._validator(models)
            runtime = self._runtime_builder(models)
        except Exception:
            raise RuntimeError(
                "模型连接测试失败，请检查 Provider、模型 ID、API Key 与结构化输出支持。"
            ) from None

        with self._lock:
            self._purge_expired()
            next_version = (self._current.config.version if self._current else 0) + 1
            public = self._public_config(
                auth_mode="api",
                chat_model_id=chat_model_id,
                assessment_model_id=assessment_model_id,
                api_key_configured={provider: True for provider in sorted(providers)},
                version=next_version,
            )
            test_id = uuid.uuid4().hex
            expires_at = self._now() + self._candidate_ttl
            self._pending[test_id] = _PendingCandidate(
                expires_at=expires_at,
                models=models,
                runtime=runtime,
                config=public,
                env_export=build_env_export(
                    chat_model_id=chat_model_id,
                    assessment_model_id=assessment_model_id,
                    api_keys=api_keys,
                    api_base_urls=dict(settings.api_base_urls or {}),
                ),
            )
            while len(self._pending) > self._max_candidates:
                self._pending.popitem(last=False)
            return TestedRuntimeModelConfig(
                test_id=test_id,
                expires_at=expires_at,
                config=public,
            )

    def apply_tested(self, test_id: str) -> RuntimeModelVersion:
        normalized_id = test_id.strip()
        with self._lock:
            candidate = self._pending.pop(normalized_id, None)
            if candidate is None:
                raise ValueError("test_id 无效或已使用。")
            if candidate.expires_at <= self._now():
                raise ValueError("test_id 已过期，请重新测试。")
            version = (self._current.config.version if self._current else 0) + 1
            config = candidate.config.model_copy(update={"version": version})
            self._current = RuntimeModelVersion(
                config=config,
                models=candidate.models,
                runtime=candidate.runtime,
            )
            self._last_env_export = dict(candidate.env_export)
            return self._current

    def take_last_env_export(self) -> dict[str, str]:
        """Return and clear the env values captured by the last apply."""

        with self._lock:
            export = self._last_env_export
            self._last_env_export = {}
            return export

    def apply_cli(
        self,
        *,
        chat_model_id: str,
        assessment_model_id: str | None,
    ) -> RuntimeModelVersion:
        normalized_chat = _model_id(chat_model_id)
        normalized_assessment = _model_id(assessment_model_id or normalized_chat)
        providers = {
            model_provider(normalized_chat),
            model_provider(normalized_assessment),
        }
        unsupported = providers - CLI_PROVIDERS
        if unsupported:
            raise ValueError(
                "CLI 配置不支持模型 Provider："
                + "、".join(sorted(unsupported))
                + "。"
            )
        settings = ModelSettings(
            chat_model_id=normalized_chat,
            assessment_model_id=normalized_assessment,
        )
        try:
            models = self._models_builder(settings, {})
            runtime = self._runtime_builder(models)
        except Exception:
            raise RuntimeError(
                "CLI 模型配置失败，请检查官方 CLI 是否已安装并完成登录。"
            ) from None

        with self._lock:
            version = (self._current.config.version if self._current else 0) + 1
            config = self._public_config(
                auth_mode="cli",
                chat_model_id=normalized_chat,
                assessment_model_id=normalized_assessment,
                api_key_configured={},
                version=version,
            )
            self._current = RuntimeModelVersion(config, models, runtime)
            self._last_env_export = build_env_export(
                chat_model_id=normalized_chat,
                assessment_model_id=normalized_assessment,
            )
            return self._current

    def _purge_expired(self) -> None:
        now = self._now()
        expired = [
            test_id
            for test_id, candidate in self._pending.items()
            if candidate.expires_at <= now
        ]
        for test_id in expired:
            self._pending.pop(test_id, None)

    @staticmethod
    def _public_config(
        *,
        auth_mode: AuthMode,
        chat_model_id: str,
        assessment_model_id: str,
        api_key_configured: dict[str, bool],
        version: int,
    ) -> PublicRuntimeModelConfig:
        return PublicRuntimeModelConfig(
            auth_mode=auth_mode,
            chat_model_id=chat_model_id,
            assessment_model_id=assessment_model_id,
            chat_provider=model_provider(chat_model_id),
            assessment_provider=model_provider(assessment_model_id),
            api_key_configured=api_key_configured,
            version=version,
        )
