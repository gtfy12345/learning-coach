from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from learning_coach.model_config import (
    ApiModelConfigInput,
    RuntimeModelConfigService,
)


class FakeRuntimeFactory:
    def __init__(self) -> None:
        self.seen: list[tuple[Any, dict[str, str]]] = []

    def build_models(self, settings: Any, api_keys: dict[str, str]) -> Any:
        self.seen.append((settings, dict(api_keys)))
        return SimpleNamespace(name=settings.chat_model_id)

    @staticmethod
    def build_graph(models: Any) -> Any:
        return SimpleNamespace(model_name=models.name)


def api_input(secret: str = "sk-super-secret") -> ApiModelConfigInput:
    return ApiModelConfigInput(
        chat_model_id="openai:gpt-5-mini",
        assessment_model_id="anthropic:claude-sonnet-4-6",
        api_keys={"openai": secret, "anthropic": "anthropic-secret"},
    )


def make_service(
    *, now: list[datetime] | None = None, validator=None
) -> tuple[RuntimeModelConfigService, FakeRuntimeFactory]:
    factory = FakeRuntimeFactory()
    service = RuntimeModelConfigService(
        models_builder=factory.build_models,
        runtime_builder=factory.build_graph,
        validator=validator or (lambda models: None),
        now=(lambda: now[0]) if now is not None else None,
    )
    service.install_initial(
        models=SimpleNamespace(name="initial"),
        runtime=SimpleNamespace(model_name="initial"),
        chat_model_id="codex_cli:default",
        assessment_model_id="codex_cli:default",
        auth_mode="cli",
    )
    return service, factory


def test_api_candidate_is_private_and_only_applies_after_successful_test() -> None:
    service, factory = make_service()
    secret = "sk-never-return-this"

    tested = service.test_api_config(api_input(secret))

    assert factory.seen[0][1]["openai"] == secret
    assert secret not in tested.model_dump_json()
    assert tested.config.api_key_configured == {
        "anthropic": True,
        "openai": True,
    }
    assert service.current().config.chat_model_id == "codex_cli:default"

    applied = service.apply_tested(tested.test_id)

    assert applied.config.version == 2
    assert applied.config.chat_model_id == "openai:gpt-5-mini"
    assert applied.runtime.model_name == "openai:gpt-5-mini"
    with pytest.raises(ValueError, match="无效或已使用"):
        service.apply_tested(tested.test_id)


def test_api_candidate_requires_each_selected_provider_key() -> None:
    service, _ = make_service()

    with pytest.raises(ValueError, match="anthropic"):
        service.test_api_config(
            ApiModelConfigInput(
                chat_model_id="openai:gpt-5-mini",
                assessment_model_id="anthropic:claude-sonnet-4-6",
                api_keys={"openai": "only-one-key"},
            )
        )


def test_failed_api_test_preserves_current_runtime_and_redacts_secret() -> None:
    secret = "sk-sensitive-failure"

    def fail(_models: Any) -> None:
        raise RuntimeError(f"provider rejected {secret}")

    service, _ = make_service(validator=fail)

    with pytest.raises(RuntimeError) as captured:
        service.test_api_config(api_input(secret))

    assert secret not in str(captured.value)
    assert service.current().config.chat_model_id == "codex_cli:default"


def test_candidate_expires_after_five_minutes() -> None:
    now = [datetime(2026, 8, 17, 12, 0, tzinfo=UTC)]
    service, _ = make_service(now=now)
    tested = service.test_api_config(api_input())

    assert tested.expires_at == now[0] + timedelta(minutes=5)
    now[0] += timedelta(minutes=5, seconds=1)

    with pytest.raises(ValueError, match="已过期"):
        service.apply_tested(tested.test_id)


def test_candidate_cache_keeps_at_most_eight_newest_entries() -> None:
    service, _ = make_service()
    test_ids = [service.test_api_config(api_input(f"secret-{i}")).test_id for i in range(9)]

    with pytest.raises(ValueError, match="无效或已使用"):
        service.apply_tested(test_ids[0])
    assert service.pending_candidate_count == 8


def test_cli_runtime_can_be_applied_without_api_secrets() -> None:
    service, factory = make_service()

    applied = service.apply_cli(
        chat_model_id="claude_code:default",
        assessment_model_id=None,
    )

    assert applied.config.auth_mode == "cli"
    assert applied.config.chat_provider == "claude_code"
    assert applied.config.assessment_model_id == "claude_code:default"
    assert applied.config.api_key_configured == {}
    assert factory.seen[-1][1] == {}
