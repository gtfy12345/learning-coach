"""Node-level retry and cache policies for the learning graph.

Retry only covers transient provider failures so configuration and validation
errors keep failing fast; cache only covers the pure diagnostic node so its
replay never leaks another session's runtime context.
"""

import hashlib
from collections.abc import Mapping
from typing import Any

from langgraph.types import RetryPolicy

TRANSIENT_ERROR_NAMES = frozenset(
    {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "ServiceUnavailableError",
        "OverloadedError",
    }
)

GRAPH_NODE_CACHE_ENV = "GRAPH_NODE_CACHE"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def is_transient_model_error(error: BaseException) -> bool:
    """Classify provider-side transient failures without importing providers."""

    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return type(error).__name__ in TRANSIENT_ERROR_NAMES


def retry_transient_model_errors(error: BaseException) -> bool:
    """Retry callback for node-level RetryPolicy."""

    return is_transient_model_error(error)


def default_model_retry_policy() -> RetryPolicy:
    """One bounded retry for transient model failures per node attempt set."""

    return RetryPolicy(
        initial_interval=0.5,
        backoff_factor=2.0,
        max_interval=4.0,
        max_attempts=2,
        retry_on=retry_transient_model_errors,
    )


def node_cache_enabled(environ: Mapping[str, str]) -> bool:
    """Read GRAPH_NODE_CACHE; caching stays on unless explicitly disabled."""

    raw_value = environ.get(GRAPH_NODE_CACHE_ENV, "true").strip().lower()
    if raw_value in _TRUE_VALUES:
        return True
    if raw_value in _FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{GRAPH_NODE_CACHE_ENV} 只接受 true 或 false。"
    )


def _image_fingerprint(images: Any) -> str:
    parts: list[str] = []
    for image in images or []:
        if isinstance(image, Mapping):
            parts.append(str(image.get("base64", "")))
        else:
            parts.append(str(image))
    return "\x1f".join(parts)


def diagnostic_cache_key(state: Mapping[str, Any]) -> str:
    """Cache the diagnostic update by topic and diagnostic image content."""

    topic = str(state.get("topic", ""))
    fingerprint = _image_fingerprint(state.get("diagnostic_images", []))
    digest = hashlib.sha256(
        f"{topic}\x1f{fingerprint}".encode("utf-8")
    ).hexdigest()
    return f"diagnostic:{digest}"
