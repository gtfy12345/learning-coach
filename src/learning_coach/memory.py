"""Durable checkpoints, cross-session learner memory, and time travel helpers.

The graph stays in-process by default; pointing ``CHECKPOINT_DB_PATH`` or
``MEMORY_DB_PATH`` at SQLite files switches the checkpointer and the long-term
memory store to durable components. Time travel reads the checkpointer only:
milestones are safe projections and forks copy a snapshot into a new thread
without touching the original session.
"""

import os
import sqlite3
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from langgraph.config import get_store
from langgraph.types import RunnableConfig

from learning_coach.schemas import (
    CheckpointMilestone,
    LearnerMemoryView,
    LearningEvent,
)

CHECKPOINT_DB_PATH_ENV = "CHECKPOINT_DB_PATH"
MEMORY_DB_PATH_ENV = "MEMORY_DB_PATH"
EXECUTION_APPROVAL_ENV = "CODE_EXECUTION_APPROVAL"

_MEMORY_FLAG_VALUES = {
    "1": True, "true": True, "yes": True, "on": True,
    "0": False, "false": False, "no": False, "off": False,
}

DEFAULT_LEARNER_ID = "local-learner"
MAX_MEMORY_SESSIONS = 20
MAX_MILESTONES = 20

MEMORY_NAMESPACE = "learner_memory"
PROFILE_KEY = "profile"
SESSION_KEY_PREFIX = "session:"
QUESTION_NAMESPACE = "question_history"
MAX_QUESTION_HISTORY = 50

_FORKABLE_NODES = frozenset(
    {"collect_diagnostic", "collect_quiz", "approve_execution"}
)
_FORK_ENTRY_PREDECESSOR = {
    "collect_diagnostic": "make_diagnostic",
    "collect_quiz": "make_quiz",
    "approve_execution": "collect_quiz",
}
_MILESTONE_LABELS: dict[str, tuple[str, str]] = {
    "recall_memory": ("会话开始", "diagnostic"),
    "make_diagnostic": ("诊断生成前", "diagnostic"),
    "collect_diagnostic": ("等待诊断回答", "diagnostic"),
    "teach": ("讲解前", "teach"),
    "prepare_practice": ("练习准备前", "quiz"),
    "make_quiz": ("练习生成前", "quiz"),
    "collect_quiz": ("等待练习回答", "quiz"),
    "approve_execution": ("等待代码执行审批", "approval"),
    "assess": ("评价前", "assessment"),
    "summarize": ("总结前", "summary"),
    "remember_session": ("记忆写入前", "summary"),
    "__end__": ("会话已完成", "summary"),
}


def _memory_flag(environ: Mapping[str, str], name: str, default: str) -> bool:
    raw_value = environ.get(name, default).strip().lower()
    if raw_value in _MEMORY_FLAG_VALUES:
        return _MEMORY_FLAG_VALUES[raw_value]
    raise RuntimeError(f"{name} 只接受 true 或 false。")


def execution_approval_enabled(environ: Mapping[str, str]) -> bool:
    """Read CODE_EXECUTION_APPROVAL; the execution gate stays on by default."""

    return _memory_flag(environ, EXECUTION_APPROVAL_ENV, "true")


def _sqlite_connection(path: str, *, autocommit: bool) -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    kwargs: dict[str, Any] = {"check_same_thread": False}
    if autocommit:
        kwargs["isolation_level"] = None
    return sqlite3.connect(path, **kwargs)


def create_checkpointer(environ: Mapping[str, str]) -> Any:
    """Build the graph checkpointer: in-memory by default, SQLite by path."""

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.checkpoint.sqlite import SqliteSaver

    path = environ.get(CHECKPOINT_DB_PATH_ENV, "").strip()
    if not path or path.lower() == "memory":
        return InMemorySaver()
    saver = SqliteSaver(_sqlite_connection(path, autocommit=False))
    saver.setup()
    return saver


def create_memory_store(environ: Mapping[str, str]) -> Any:
    """Build the long-term memory store: in-memory by default, SQLite by path."""

    from langgraph.store.memory import InMemoryStore

    path = environ.get(MEMORY_DB_PATH_ENV, "").strip()
    if not path or path.lower() == "memory":
        return InMemoryStore()
    from langgraph.store.sqlite import SqliteStore

    store = SqliteStore(_sqlite_connection(path, autocommit=True))
    store.setup()
    return store


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _learner_namespace_for(namespace: str, learner_id: str) -> tuple[str, str]:
    return (namespace, (learner_id or DEFAULT_LEARNER_ID).strip() or DEFAULT_LEARNER_ID)


def _learner_namespace(learner_id: str) -> tuple[str, str]:
    return _learner_namespace_for(MEMORY_NAMESPACE, learner_id)


def record_learning_memory(
    store: Any, learner_id: str, thread_id: str, values: Mapping[str, Any]
) -> LearnerMemoryView:
    """Persist one finished session and refresh the aggregated profile.

    The session key is derived from the thread id, so replaying a crashed
    write overwrites the same entry instead of duplicating it.
    """

    session_value = {
        "topic": str(values.get("topic", ""))[:100],
        "score": int(values.get("score") or 0),
        "attempts": int(values.get("attempts") or 0),
        "missing_point": str(values.get("missing_point") or "")[:200],
        "recent_errors": [
            str(error)[:100]
            for error in (values.get("recent_errors") or [])[:3]
        ],
        "updated_at": _utc_now_iso(),
    }
    store.put(_learner_namespace(learner_id), f"{SESSION_KEY_PREFIX}{thread_id}", session_value)
    sessions = sorted(
        (
            item
            for item in store.search(_learner_namespace(learner_id), limit=200)
            if item.key.startswith(SESSION_KEY_PREFIX)
        ),
        key=lambda item: str(item.value.get("updated_at", "")),
    )
    recent = sessions[-MAX_MEMORY_SESSIONS:]
    topics: list[str] = []
    for item in recent:
        topic = str(item.value.get("topic", ""))
        if topic and topic not in topics:
            topics.append(topic)
    profile = LearnerMemoryView(
        sessions=len(recent),
        topics=topics[-20:],
        average_score=(
            round(sum(int(item.value.get("score") or 0) for item in recent) / len(recent))
            if recent
            else 0
        ),
        last_topic=str(recent[-1].value.get("topic", ""))[:100] if recent else "",
        last_missing_point=(
            str(recent[-1].value.get("missing_point") or "")[:200] if recent else ""
        ),
        updated_at=_utc_now_iso(),
    )
    store.put(_learner_namespace(learner_id), PROFILE_KEY, profile.model_dump(mode="json"))
    return profile


def recall_learning_memory(store: Any, learner_id: str) -> dict[str, Any]:
    """Read the aggregated learner profile, or an empty dict when absent."""

    if store is None:
        return {}
    item = store.get(_learner_namespace(learner_id), PROFILE_KEY)
    return dict(item.value) if item is not None else {}


def record_question_history(
    store: Any,
    learner_id: str,
    *,
    topic: str,
    learning_goal: str = "",
    source: str = "session",
) -> str:
    """Record one learner-submitted question at session creation time."""

    created_at = _utc_now_iso()
    key = f"{created_at}:{time.time_ns():022d}"
    store.put(
        _learner_namespace_for(QUESTION_NAMESPACE, learner_id),
        key,
        {
            "topic": str(topic)[:500],
            "learning_goal": str(learning_goal)[:1_000],
            "source": str(source)[:30],
            "created_at": created_at,
        },
    )
    return key


def list_question_history(
    store: Any, learner_id: str, limit: int = MAX_QUESTION_HISTORY
) -> list[dict[str, Any]]:
    """Return the learner's submitted questions, newest first."""

    if store is None:
        return []
    if limit <= 0:
        raise ValueError("limit 必须是正整数。")
    items = store.search(
        _learner_namespace_for(QUESTION_NAMESPACE, learner_id), limit=200
    )
    ordered = sorted(
        items,
        key=lambda item: (str(item.value.get("created_at", "")), item.key),
        reverse=True,
    )[:limit]
    return [
        {
            "topic": str(item.value.get("topic", "")),
            "learning_goal": str(item.value.get("learning_goal", "")),
            "source": str(item.value.get("source", "session")),
            "created_at": str(item.value.get("created_at", "")),
        }
        for item in ordered
    ]


def memory_summary_line(memory: Mapping[str, Any] | None) -> str:
    """One bounded deterministic line describing the long-term memory."""

    if not isinstance(memory, Mapping) or not memory.get("sessions"):
        return ""
    topics = memory.get("topics") or []
    recent = "、".join(str(topic) for topic in topics[-3:])
    return (
        f"长期记忆：已学 {memory.get('sessions', 0)} 个主题"
        f"（平均 {memory.get('average_score', 0)} 分）"
        + (f"，最近：{recent}" if recent else "")
    )


def _current_store() -> Any:
    try:
        return get_store()
    except RuntimeError:
        return None


def recall_memory_node(state: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """Graph node: load the learner profile before the session starts."""

    del config
    memory = recall_learning_memory(
        _current_store(), str(state.get("learner_id") or DEFAULT_LEARNER_ID)
    )
    if not memory:
        return {}
    detail = memory_summary_line(memory)
    return {
        "long_term_memory": memory,
        "learning_events": [
            LearningEvent(
                node="recall_memory", detail=detail[:200]
            ).model_dump(mode="json")
        ],
    }


def remember_session_node(state: Mapping[str, Any], config: RunnableConfig) -> dict[str, Any]:
    """Graph node: persist the finished session with an idempotent key."""

    store = _current_store()
    if store is None:
        return {}
    thread_id = str(
        (config.get("configurable") or {}).get("thread_id", "")
    )
    if not thread_id:
        return {}
    profile = record_learning_memory(
        store,
        str(state.get("learner_id") or DEFAULT_LEARNER_ID),
        thread_id,
        state,
    )
    return {
        "learning_events": [
            LearningEvent(
                node="remember_session",
                detail=(
                    f"会话记忆已保存 · 累计 {profile.sessions} 次"
                    f" · 平均 {profile.average_score} 分"
                )[:200],
            ).model_dump(mode="json")
        ],
    }


def list_session_checkpoints(
    graph: Any, config: Mapping[str, Any], limit: int = MAX_MILESTONES
) -> list[CheckpointMilestone]:
    """Project the thread's checkpoint history into safe milestones."""

    if limit <= 0:
        raise ValueError("limit 必须是正整数。")
    milestones: list[CheckpointMilestone] = []
    for snapshot in graph.get_state_history(dict(config)):
        next_nodes = snapshot.next or ()
        node = next_nodes[0] if next_nodes else "__end__"
        label, stage = _MILESTONE_LABELS.get(node, ("运行中", "progress"))
        values = snapshot.values or {}
        milestones.append(
            CheckpointMilestone(
                checkpoint_id=str(
                    snapshot.config["configurable"].get("checkpoint_id", "")
                ),
                node=node,
                label=label,
                stage=stage,
                attempts=values.get("attempts"),
                score=values.get("score"),
                forkable=node in _FORKABLE_NODES,
            )
        )
        if len(milestones) >= limit:
            break
    return milestones


def fork_session(
    graph: Any,
    config: Mapping[str, Any],
    checkpoint_id: str,
    fork_thread_id: str,
) -> dict[str, Any]:
    """Copy one snapshot into a new thread and re-enter its pending node.

    The original thread is never modified: the fork seeds a fresh thread with
    the snapshot values attributed to the predecessor of the pending node, so
    the next run lands on the same interrupt with the historical state.
    """

    if not checkpoint_id:
        raise ValueError("checkpoint_id 不能为空。")
    if not fork_thread_id:
        raise ValueError("fork_thread_id 不能为空。")
    target = None
    for snapshot in graph.get_state_history(dict(config)):
        if str(snapshot.config["configurable"].get("checkpoint_id", "")) == checkpoint_id:
            target = snapshot
            break
    if target is None:
        raise LookupError("找不到指定的检查点。")
    next_nodes = target.next or ()
    entry = next_nodes[0] if next_nodes else ""
    as_node = _FORK_ENTRY_PREDECESSOR.get(entry)
    if as_node is None:
        raise ValueError("该检查点不支持分叉；只能从等待输入的检查点分叉。")
    fork_config: dict[str, Any] = {
        "configurable": {"thread_id": fork_thread_id}
    }
    graph.update_state(fork_config, dict(target.values), as_node=as_node)
    return {
        "fork_config": fork_config,
        "entry_node": entry,
        "baseline": dict(target.values),
    }


_COMPARISON_FIELDS = (
    "score",
    "attempts",
    "mastery_level",
    "recent_errors",
    "missing_point",
    "feedback",
    "topic",
)


def compare_learning_states(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Diff safe learning fields between two state snapshots."""

    changes: dict[str, dict[str, Any]] = {}
    for field in _COMPARISON_FIELDS:
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value != new_value:
            changes[field] = {"before": old_value, "after": new_value}
    return changes
