from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from learning_coach.model import (
    LearningCoachModels,
    ModelSettings,
    create_model_suite_from_settings,
)
from learning_coach.schemas import Assessment, Diagnostic

ApiProvider = Literal["openai", "anthropic", "google_genai"]
CliProvider = Literal["codex_cli", "claude_code"]
AuthMode = Literal["api", "cli"]

API_PROVIDERS = frozenset({"openai", "anthropic", "google_genai"})
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


class ApiModelConfigInput(BaseModel):
    chat_model_id: str = Field(min_length=3, max_length=200)
    assessment_model_id: str | None = Field(default=None, max_length=200)
    api_keys: dict[str, SecretStr]

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
            return self._current

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
