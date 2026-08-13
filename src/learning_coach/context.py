from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


DEFAULT_MODEL_CALL_LIMIT = 3
DEFAULT_TOOL_CALL_LIMIT = 2
MAX_MODEL_CALL_LIMIT = 10
MAX_TOOL_CALL_LIMIT = 8
MAX_LEARNING_GOAL_LENGTH = 1_000
MAX_CONTEXT_SUMMARY_LENGTH = 600
MAX_RECENT_ERRORS = 3

MasteryBand = Literal["foundation", "developing", "mastered"]


def _bounded_int(
    environ: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} 必须是 {minimum} 到 {maximum} 之间的整数。"
        ) from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name} 必须是 {minimum} 到 {maximum} 之间的整数。"
        )
    return value


@dataclass(frozen=True)
class LearningContextSettings:
    """Server-owned hard limits for one context-engineered teaching run."""

    model_call_limit: int = DEFAULT_MODEL_CALL_LIMIT
    tool_call_limit: int = DEFAULT_TOOL_CALL_LIMIT

    def __post_init__(self) -> None:
        if not 1 <= self.model_call_limit <= MAX_MODEL_CALL_LIMIT:
            raise ValueError(
                f"model_call_limit 必须是 1 到 {MAX_MODEL_CALL_LIMIT} 之间的整数。"
            )
        if not 0 <= self.tool_call_limit <= MAX_TOOL_CALL_LIMIT:
            raise ValueError(
                f"tool_call_limit 必须是 0 到 {MAX_TOOL_CALL_LIMIT} 之间的整数。"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str]
    ) -> "LearningContextSettings":
        return cls(
            model_call_limit=_bounded_int(
                environ,
                "CONTEXT_MODEL_CALL_LIMIT",
                DEFAULT_MODEL_CALL_LIMIT,
                minimum=1,
                maximum=MAX_MODEL_CALL_LIMIT,
            ),
            tool_call_limit=_bounded_int(
                environ,
                "CONTEXT_TOOL_CALL_LIMIT",
                DEFAULT_TOOL_CALL_LIMIT,
                minimum=0,
                maximum=MAX_TOOL_CALL_LIMIT,
            ),
        )


@dataclass(frozen=True)
class LearningRuntimeContext:
    """Immutable per-session intent and budget passed through LangGraph runtime."""

    learning_goal: str
    target_mastery: int = 80
    model_call_limit: int = DEFAULT_MODEL_CALL_LIMIT
    tool_call_limit: int = DEFAULT_TOOL_CALL_LIMIT

    def __post_init__(self) -> None:
        normalized_goal = self.learning_goal.strip()
        if not normalized_goal:
            raise ValueError("学习目标不能为空。")
        if len(normalized_goal) > MAX_LEARNING_GOAL_LENGTH:
            raise ValueError(
                f"学习目标不能超过 {MAX_LEARNING_GOAL_LENGTH} 个字符。"
            )
        if not 1 <= self.target_mastery <= 100:
            raise ValueError("目标掌握度必须是 1 到 100 之间的整数。")
        if not 1 <= self.model_call_limit <= MAX_MODEL_CALL_LIMIT:
            raise ValueError(
                f"模型调用预算必须是 1 到 {MAX_MODEL_CALL_LIMIT} 之间的整数。"
            )
        if not 0 <= self.tool_call_limit <= MAX_TOOL_CALL_LIMIT:
            raise ValueError(
                f"工具调用预算必须是 0 到 {MAX_TOOL_CALL_LIMIT} 之间的整数。"
            )
        object.__setattr__(self, "learning_goal", normalized_goal)


@dataclass(frozen=True)
class TeachingContext:
    """Bounded context projection used by teaching prompts and middleware."""

    learning_goal: str
    target_mastery: int
    mastery_level: int
    mastery_band: MasteryBand
    recent_errors: list[str]
    context_summary: str
    available_tools: list[str]
    prefer_advanced_model: bool
    model_call_limit: int
    tool_call_limit: int


_NO_ERROR_MARKERS = {"", "暂无", "无", "没有", "已经掌握", "已掌握"}


def update_recent_errors(
    existing: list[str], missing_point: str | None
) -> list[str]:
    """Keep the latest three distinct actionable knowledge gaps."""

    normalized = (missing_point or "").strip()
    errors = [value.strip() for value in existing if value.strip()]
    if normalized in _NO_ERROR_MARKERS:
        return errors[-MAX_RECENT_ERRORS:]
    errors = [value for value in errors if value != normalized]
    errors.append(normalized)
    return errors[-MAX_RECENT_ERRORS:]


def _mastery_level(value: Any) -> int:
    try:
        mastery = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, mastery))


def mastery_band(mastery_level: int) -> MasteryBand:
    if mastery_level < 60:
        return "foundation"
    if mastery_level < 80:
        return "developing"
    return "mastered"


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_context_summary(
    values: Mapping[str, Any],
    runtime: LearningRuntimeContext,
) -> str:
    """Summarize learning progress deterministically without another model call."""

    mastery = _mastery_level(values.get("mastery_level", 0))
    recent_errors = update_recent_errors(
        list(values.get("recent_errors", [])), None
    )
    errors_text = "；".join(recent_errors) or "暂无已确认错误"
    parts = [
        f"学习目标：{runtime.learning_goal}",
        f"当前主题：{_bounded_text(values.get('topic'), 100)}",
        f"当前掌握度：{mastery}/100（目标 {runtime.target_mastery}/100）",
        f"诊断重点：{_bounded_text(values.get('diagnostic_focus') or '待诊断', 100)}",
        f"最近错误：{_bounded_text(errors_text, 220)}",
        f"最新反馈：{_bounded_text(values.get('feedback') or '暂无', 180)}",
    ]
    return _bounded_text("\n".join(parts), MAX_CONTEXT_SUMMARY_LENGTH)


def build_teaching_context(
    values: Mapping[str, Any],
    runtime: LearningRuntimeContext,
) -> TeachingContext:
    """Select the smallest useful prompt, tool and model context for teaching."""

    mastery = _mastery_level(values.get("mastery_level", 0))
    errors = update_recent_errors(list(values.get("recent_errors", [])), None)
    has_material = bool(str(values.get("study_material", "")).strip())
    has_progress = any(
        str(values.get(key, "")).strip()
        for key in ("diagnostic_answer", "feedback", "missing_point")
    ) or bool(errors)
    tools: list[str] = []
    if runtime.tool_call_limit > 0:
        if has_material:
            tools.append("search_study_material")
        if has_progress:
            tools.append("inspect_learning_progress")
    return TeachingContext(
        learning_goal=runtime.learning_goal,
        target_mastery=runtime.target_mastery,
        mastery_level=mastery,
        mastery_band=mastery_band(mastery),
        recent_errors=errors,
        context_summary=build_context_summary(values, runtime),
        available_tools=tools,
        prefer_advanced_model=mastery < 60 or len(errors) >= 2,
        model_call_limit=runtime.model_call_limit,
        tool_call_limit=runtime.tool_call_limit,
    )


def create_learning_runtime_context(
    topic: str,
    *,
    learning_goal: str | None = None,
    settings: LearningContextSettings | None = None,
) -> LearningRuntimeContext:
    """Build a validated runtime context without exposing budget control to clients."""

    normalized_topic = topic.strip()
    if not normalized_topic:
        raise ValueError("学习主题不能为空。")
    context_settings = settings or LearningContextSettings()
    goal = (learning_goal or "").strip() or f"掌握主题：{normalized_topic}"
    return LearningRuntimeContext(
        learning_goal=goal,
        model_call_limit=context_settings.model_call_limit,
        tool_call_limit=context_settings.tool_call_limit,
    )
