from types import SimpleNamespace
from typing import Any

import pytest

from learning_coach import cli


class FinishedGraph:
    def __init__(self) -> None:
        self.initial_state: dict[str, Any] | None = None
        self.runtime_context: Any = None

    def invoke(
        self,
        value: dict[str, Any],
        config: dict[str, Any],
        *,
        context: Any = None,
    ) -> dict[str, Any]:
        self.initial_state = value
        self.runtime_context = context
        return {"summary": "done"}


def test_run_passes_images_into_initial_graph_state(monkeypatch) -> None:
    graph = FinishedGraph()
    block = {"type": "image", "url": "https://example.com/diagram.png"}
    monkeypatch.setattr(
        cli, "create_model_suite", lambda: SimpleNamespace(accepts_images=True)
    )
    monkeypatch.setattr(cli, "image_content_block", lambda source: block)
    monkeypatch.setattr(cli, "build_learning_graph", lambda models: graph)

    result = cli.run(
        "状态图",
        thread_id="test-thread",
        image_sources=["https://example.com/diagram.png"],
    )

    assert result["summary"] == "done"
    assert graph.initial_state == {
        "topic": "状态图",
        "attempts": 0,
        "learning_goal": "掌握主题：状态图",
        "mastery_level": 0,
        "recent_errors": [],
        "diagnostic_images": [block],
    }


def test_run_passes_learning_goal_as_state_and_runtime_context(monkeypatch) -> None:
    graph = FinishedGraph()
    monkeypatch.setattr(
        cli, "create_model_suite", lambda: SimpleNamespace(accepts_images=True)
    )
    monkeypatch.setattr(cli, "build_learning_graph", lambda models: graph)

    cli.run("LCEL", learning_goal="能独立组合 Runnable")

    assert graph.initial_state["learning_goal"] == "能独立组合 Runnable"
    assert graph.runtime_context.learning_goal == "能独立组合 Runnable"


def test_run_rejects_images_for_text_only_model(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "create_model_suite", lambda: SimpleNamespace(accepts_images=False)
    )
    monkeypatch.setattr(
        cli,
        "image_content_block",
        lambda source: {"type": "image", "url": source},
    )

    with pytest.raises(RuntimeError, match="没有声明图片输入能力"):
        cli.run("状态图", image_sources=["https://example.com/diagram.png"])


def test_main_dispatches_auth_without_treating_it_as_learning_topic(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "run_auth_action",
        lambda provider, action: calls.append((provider, action)) or 0,
    )

    cli.main(["auth", "login", "codex"])

    assert calls == [("codex", "login")]


def test_main_dispatches_web_without_treating_it_as_learning_topic(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(cli, "_run_web_cli", lambda arguments: calls.append(arguments))

    cli.main(["web", "--model", "codex_cli:default"])

    assert calls == [["--model", "codex_cli:default"]]


def test_main_accepts_optional_learning_goal(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        cli,
        "run",
        lambda topic, **kwargs: calls.append((topic, kwargs.get("learning_goal"))),
    )

    cli.main(["LCEL", "--goal", "能独立组合 Runnable"])

    assert calls == [("LCEL", "能独立组合 Runnable")]
