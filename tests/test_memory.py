import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from langgraph.types import Command

from learning_coach.context import LearningRuntimeContext, build_context_summary
from learning_coach.graph import build_learning_graph
from learning_coach.memory import (
    create_checkpointer,
    create_memory_store,
    compare_learning_states,
    execution_approval_enabled,
    fork_session,
    list_session_checkpoints,
    memory_summary_line,
    recall_learning_memory,
    recall_memory_node,
    record_learning_memory,
    remember_session_node,
)
from tests.test_graph import FakeChatModel

RUNTIME = LearningRuntimeContext(learning_goal="掌握记忆与时间旅行")


def _tmp_db(tmp_path: Path, name: str) -> str:
    return str(tmp_path / name)


def test_execution_approval_flag_parses_environment() -> None:
    assert execution_approval_enabled({}) is True
    assert execution_approval_enabled({"CODE_EXECUTION_APPROVAL": "false"}) is False
    assert execution_approval_enabled({"CODE_EXECUTION_APPROVAL": "0"}) is False
    with pytest.raises(RuntimeError):
        execution_approval_enabled({"CODE_EXECUTION_APPROVAL": "maybe"})


def test_create_checkpointer_and_store_switch_by_path(tmp_path: Path) -> None:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    assert isinstance(create_checkpointer({}), InMemorySaver)
    assert isinstance(create_memory_store({}), InMemoryStore)

    checkpoint_path = _tmp_db(tmp_path, "checkpoints.sqlite")
    memory_path = _tmp_db(tmp_path, "memory.sqlite")
    saver = create_checkpointer({"CHECKPOINT_DB_PATH": checkpoint_path})
    store = create_memory_store({"MEMORY_DB_PATH": memory_path})
    assert Path(checkpoint_path).exists()
    assert Path(memory_path).exists()
    store.put(("learner_memory", "learner-1"), "profile", {"sessions": 1})
    reopened = create_memory_store({"MEMORY_DB_PATH": memory_path})
    item = reopened.get(("learner_memory", "learner-1"), "profile")
    assert item is not None and item.value["sessions"] == 1


def test_record_memory_is_idempotent_per_thread() -> None:
    store = create_memory_store({})
    values = {
        "topic": "LangGraph 记忆",
        "score": 86,
        "attempts": 1,
        "missing_point": "还需要复习 Store 命名空间",
        "recent_errors": ["Store 命名空间"],
    }
    record_learning_memory(store, "learner-1", "thread-1", values)
    record_learning_memory(store, "learner-1", "thread-1", values)

    sessions = [
        item
        for item in store.search(("learner_memory", "learner-1"), limit=50)
        if item.key.startswith("session:")
    ]
    assert len(sessions) == 1

    record_learning_memory(store, "learner-1", "thread-2", {**values, "score": 60})
    profile = recall_learning_memory(store, "learner-1")
    assert profile["sessions"] == 2
    assert profile["average_score"] == 73
    assert profile["last_topic"] == "LangGraph 记忆"
    assert memory_summary_line(profile).startswith("长期记忆：已学 2 个主题")


def test_memory_line_injected_into_context_summary() -> None:
    summary = build_context_summary(
        {
            "topic": "记忆",
            "mastery_level": 0,
            "long_term_memory": {
                "sessions": 3,
                "topics": ["A", "B"],
                "average_score": 70,
            },
        },
        RUNTIME,
    )
    assert "长期记忆：已学 3 个主题" in summary
    assert "平均 70 分" in summary


def test_memory_nodes_noop_without_store() -> None:
    assert recall_memory_node({"topic": "记忆"}, {}) == {}
    assert remember_session_node({"topic": "记忆", "score": 80}, {}) == {}


def test_durable_resume_continues_across_graph_instances(tmp_path: Path) -> None:
    checkpoint_path = _tmp_db(tmp_path, "resume.sqlite")
    saver = create_checkpointer({"CHECKPOINT_DB_PATH": checkpoint_path})
    config = {"configurable": {"thread_id": "durable-1"}}

    first_graph = build_learning_graph(FakeChatModel(), checkpointer=saver)
    result = first_graph.invoke({"topic": "LangGraph 记忆", "attempts": 0}, config=config)
    assert result["__interrupt__"][0].value["kind"] == "diagnostic"

    second_graph = build_learning_graph(FakeChatModel(), checkpointer=saver)
    resumed = second_graph.invoke(None, config=config)
    assert resumed["__interrupt__"][0].value["kind"] == "diagnostic"
    resumed = second_graph.invoke(
        Command(resume="检查点保存每一步状态。"), config=config
    )
    assert resumed["__interrupt__"][0].value["kind"] == "quiz"
    final = second_graph.invoke(
        Command(resume="thread_id 加 checkpointer。"), config=config
    )
    assert final["score"] == 86


def test_approval_disabled_keeps_direct_execution(monkeypatch) -> None:
    monkeypatch.setenv("CODE_EXECUTION_APPROVAL", "false")
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "no-approval"}}

    graph.invoke({"topic": "Python 函数", "attempts": 0}, config=config)
    graph.invoke(Command(resume="函数映射输入。"), config=config)
    result = graph.invoke(
        Command(
            resume="def clamp_score(score):\n    return min(100, max(0, score))\n"
        ),
        config=config,
    )

    assert "__interrupt__" not in result or result["__interrupt__"][0].value[
        "kind"
    ] != "approval"
    assert result["score"] == 100
    assert result["code_practice_report"]["status"] == "passed"


def test_milestones_are_bounded_safe_and_labeled() -> None:
    graph = build_learning_graph(FakeChatModel())
    config = {"configurable": {"thread_id": "milestones"}}

    graph.invoke({"topic": "LangGraph 记忆", "attempts": 0}, config=config)
    result = graph.invoke(Command(resume="检查点按步保存。"), config=config)

    milestones = list_session_checkpoints(graph, config)
    assert 1 <= len(milestones) <= 20
    labels = {item.label for item in milestones}
    assert "等待诊断回答" in labels
    assert "等待练习回答" in labels
    quiz = next(
        item for item in milestones if item.node == "collect_quiz"
    )
    assert quiz.forkable is True
    assert quiz.stage == "quiz"
    serialized = str([item.model_dump(mode="json") for item in milestones])
    assert "quiz_answer" not in serialized
    assert "explanation" not in serialized
    with pytest.raises(ValueError):
        list_session_checkpoints(graph, config, limit=0)


def test_fork_reenters_interrupt_and_keeps_original_intact() -> None:
    from tests.test_graph import ScriptedFakeChatModel

    graph = build_learning_graph(ScriptedFakeChatModel(scores=[86]))
    config = {"configurable": {"thread_id": "fork-origin"}}
    graph.invoke({"topic": "LangGraph 分叉", "attempts": 0}, config=config)
    result = graph.invoke(Command(resume="原回答。"), config=config)
    assert result["__interrupt__"][0].value["kind"] == "quiz"

    milestones = list_session_checkpoints(graph, config)
    quiz_checkpoint = next(
        item for item in milestones if item.node == "collect_quiz"
    )
    fork = fork_session(
        graph, config, quiz_checkpoint.checkpoint_id, "fork-branch-1"
    )
    assert fork["entry_node"] == "collect_quiz"

    fork_result = graph.invoke(None, config=fork["fork_config"])
    assert fork_result["__interrupt__"][0].value["kind"] == "quiz"
    final = graph.invoke(
        Command(resume="分叉后的新回答。"), config=fork["fork_config"]
    )
    assert final["score"] == 86
    assert final["quiz_answer"] == "分叉后的新回答。"

    original_state = graph.get_state(config)
    assert original_state.next == ("collect_quiz",)
    assert original_state.values["diagnostic_answer"] == "原回答。"

    original_result = graph.invoke(
        Command(resume="原线程的练习回答。"), config=config
    )
    assert original_result["score"] == 86
    comparison = compare_learning_states(fork["baseline"], original_result)
    assert "quiz_answer" not in comparison
    with pytest.raises(LookupError):
        fork_session(graph, config, "missing-checkpoint", "fork-2")


def test_compare_states_reports_safe_field_diffs() -> None:
    before = {
        "score": 55,
        "attempts": 1,
        "mastery_level": 55,
        "recent_errors": ["a"],
        "missing_point": "a",
        "feedback": "f1",
        "topic": "t",
    }
    after = {**before, "score": 86, "attempts": 2, "mastery_level": 86}
    changes = compare_learning_states(before, after)
    assert set(changes) == {"score", "attempts", "mastery_level"}
    assert changes["score"] == {"before": 55, "after": 86}


def test_public_docs_describe_memory_and_time_travel_contract() -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    env_example = (
        Path(__file__).parents[1] / ".env.example"
    ).read_text(encoding="utf-8")

    for term in (
        "CHECKPOINT_DB_PATH",
        "MEMORY_DB_PATH",
        "CODE_EXECUTION_APPROVAL",
        "长期记忆",
        "Time Travel",
        "分叉",
        "审批",
        "--thread-id",
        "幂等",
    ):
        assert term in readme
    for term in (
        "CHECKPOINT_DB_PATH",
        "MEMORY_DB_PATH",
        "CODE_EXECUTION_APPROVAL",
    ):
        assert term in env_example
