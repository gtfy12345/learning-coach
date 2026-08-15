from typing import Any, Callable

import pytest
from langchain_core.messages import AIMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import RetryPolicy

from learning_coach.graph import build_learning_graph
from learning_coach.resilience import (
    default_model_retry_policy,
    diagnostic_cache_key,
    is_transient_model_error,
    node_cache_enabled,
    retry_transient_model_errors,
)
from learning_coach.schemas import Assessment, Diagnostic


class RateLimitError(Exception):
    """Provider-shaped transient error used without importing a provider."""


class FailingStructuredModel:
    """Structured fake that can fail the first N diagnostic calls."""

    def __init__(self, owner: "FailingFakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, messages: Any) -> Diagnostic | Assessment:
        if self.schema is Diagnostic:
            self.owner.diagnostic_calls += 1
            if self.owner.diagnostic_calls <= self.owner.diagnostic_failures:
                raise self.owner.diagnostic_error_factory()
            return Diagnostic(
                question="节点缓存键应包含哪些输入？",
                focus="节点缓存",
                difficulty="foundation",
            )
        assert self.schema is Assessment
        return Assessment(
            score=90,
            feedback="已经说明缓存键的组成。",
            missing_point="无",
        )


class FailingFakeChatModel:
    def __init__(
        self,
        *,
        diagnostic_failures: int = 0,
        diagnostic_error_factory: Callable[[], Exception] = lambda: RateLimitError(
            "rate limited"
        ),
    ) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.diagnostic_failures = diagnostic_failures
        self.diagnostic_error_factory = diagnostic_error_factory
        self.diagnostic_calls = 0
        self.responses = iter(
            [
                "默认覆盖会让并行写入丢失，Reducer 定义合并规则。",
                "请说明哪些错误适合节点级重试。",
                "你已经理解重试与缓存的边界。",
            ]
        )

    def invoke(self, messages: Any) -> AIMessage:
        return AIMessage(content=next(self.responses))

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FailingStructuredModel:
        return FailingStructuredModel(self, schema)


def fast_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        initial_interval=0.0,
        max_attempts=2,
        retry_on=retry_transient_model_errors,
    )


def test_is_transient_model_error_classifies_common_failures() -> None:
    assert is_transient_model_error(TimeoutError("upstream timeout"))
    assert is_transient_model_error(ConnectionError("reset by peer"))
    assert is_transient_model_error(RateLimitError("rate limited"))
    assert not is_transient_model_error(ValueError("bad config"))
    assert not is_transient_model_error(RuntimeError("validation failed"))
    assert not is_transient_model_error(GraphBubbleUp())


def test_default_retry_policy_is_bounded_and_transient_only() -> None:
    policy = default_model_retry_policy()
    assert policy.max_attempts == 2
    assert policy.initial_interval == 0.5
    assert policy.retry_on is retry_transient_model_errors
    assert not retry_transient_model_errors(ValueError("bad config"))


def test_transient_diagnostic_failure_retries_and_reaches_interrupt() -> None:
    model = FailingFakeChatModel(diagnostic_failures=1)
    graph = build_learning_graph(model, retry_policy=fast_retry_policy())
    config = {"configurable": {"thread_id": "transient-retry-session"}}

    result = graph.invoke({"topic": "节点重试", "attempts": 0}, config=config)

    assert model.diagnostic_calls == 2
    assert result["__interrupt__"][0].value["kind"] == "diagnostic"


def test_non_transient_diagnostic_failure_fails_fast() -> None:
    model = FailingFakeChatModel(
        diagnostic_failures=1,
        diagnostic_error_factory=lambda: ValueError("model misconfigured"),
    )
    graph = build_learning_graph(model, retry_policy=fast_retry_policy())
    config = {"configurable": {"thread_id": "fail-fast-session"}}

    with pytest.raises(ValueError, match="model misconfigured"):
        graph.invoke({"topic": "节点重试", "attempts": 0}, config=config)
    assert model.diagnostic_calls == 1


def test_persistent_transient_failure_stops_at_max_attempts() -> None:
    model = FailingFakeChatModel(diagnostic_failures=99)
    graph = build_learning_graph(model, retry_policy=fast_retry_policy())
    config = {"configurable": {"thread_id": "exhausted-retry-session"}}

    with pytest.raises(RateLimitError, match="rate limited"):
        graph.invoke({"topic": "节点重试", "attempts": 0}, config=config)
    assert model.diagnostic_calls == 2


def test_node_cache_enabled_parses_environment_switch() -> None:
    assert node_cache_enabled({})
    assert node_cache_enabled({"GRAPH_NODE_CACHE": "true"})
    assert node_cache_enabled({"GRAPH_NODE_CACHE": "1"})
    assert not node_cache_enabled({"GRAPH_NODE_CACHE": "false"})
    assert not node_cache_enabled({"GRAPH_NODE_CACHE": "0"})
    with pytest.raises(RuntimeError):
        node_cache_enabled({"GRAPH_NODE_CACHE": "maybe"})


def test_diagnostic_cache_key_reflects_topic_and_images() -> None:
    base = {"topic": "LangGraph Reducer"}
    assert diagnostic_cache_key(base) == diagnostic_cache_key(dict(base))
    assert diagnostic_cache_key(base) != diagnostic_cache_key(
        {"topic": "LangGraph Command"}
    )
    with_image = {
        "topic": "LangGraph Reducer",
        "diagnostic_images": [
            {"type": "image", "base64": "aW1hZ2U=", "mime_type": "image/png"}
        ],
    }
    other_image = {
        "topic": "LangGraph Reducer",
        "diagnostic_images": [
            {"type": "image", "base64": "b3RoZXI=", "mime_type": "image/png"}
        ],
    }
    assert diagnostic_cache_key(base) != diagnostic_cache_key(with_image)
    assert diagnostic_cache_key(with_image) != diagnostic_cache_key(other_image)


def test_second_session_with_same_topic_reuses_cached_diagnostic() -> None:
    model = FailingFakeChatModel()
    graph = build_learning_graph(model, enable_node_cache=True)

    first = graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
        config={"configurable": {"thread_id": "cache-first"}},
    )
    second = graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
        config={"configurable": {"thread_id": "cache-second"}},
    )

    assert model.diagnostic_calls == 1
    assert first["diagnostic_question"] == second["diagnostic_question"]
    assert second["__interrupt__"][0].value["kind"] == "diagnostic"


def test_node_cache_disabled_regenerates_diagnostic() -> None:
    model = FailingFakeChatModel()
    graph = build_learning_graph(model, enable_node_cache=False)

    graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
        config={"configurable": {"thread_id": "nocache-first"}},
    )
    graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
        config={"configurable": {"thread_id": "nocache-second"}},
    )

    assert model.diagnostic_calls == 2


def test_different_topics_do_not_share_diagnostic_cache() -> None:
    model = FailingFakeChatModel()
    graph = build_learning_graph(model, enable_node_cache=True)

    graph.invoke(
        {"topic": "LangGraph Reducer", "attempts": 0},
        config={"configurable": {"thread_id": "cache-topic-a"}},
    )
    graph.invoke(
        {"topic": "LangGraph Command", "attempts": 0},
        config={"configurable": {"thread_id": "cache-topic-b"}},
    )

    assert model.diagnostic_calls == 2


def test_different_images_do_not_share_diagnostic_cache() -> None:
    model = FailingFakeChatModel()
    graph = build_learning_graph(model, enable_node_cache=True)

    graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "attempts": 0,
            "diagnostic_images": [
                {"type": "image", "base64": "aW1hZ2U=", "mime_type": "image/png"}
            ],
        },
        config={"configurable": {"thread_id": "cache-image-a"}},
    )
    graph.invoke(
        {
            "topic": "LangGraph Reducer",
            "attempts": 0,
            "diagnostic_images": [
                {"type": "image", "base64": "b3RoZXI=", "mime_type": "image/png"}
            ],
        },
        config={"configurable": {"thread_id": "cache-image-b"}},
    )

    assert model.diagnostic_calls == 2


def test_public_docs_describe_advanced_state_runtime_contract() -> None:
    from pathlib import Path

    readme = (Path(__file__).parents[1] / "README.md").read_text(
        encoding="utf-8"
    )
    env_example = (
        Path(__file__).parents[1] / ".env.example"
    ).read_text(encoding="utf-8")

    for term in (
        "Command",
        "Reducer",
        "RetryPolicy",
        "CachePolicy",
        "GRAPH_NODE_CACHE",
        "并行 fan-out",
        "瞬态",
        "learning_events",
        "顺序不保证",
    ):
        assert term in readme
    assert "GRAPH_NODE_CACHE=true" in env_example
    assert "GRAPH_NODE_CACHE=false" in readme
