import os
from typing import Any

from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import CachePolicy, RetryPolicy

from learning_coach.agents import build_teaching_swarm, resolve_teaching_retriever
from learning_coach.context import LearningRuntimeContext
from learning_coach.nodes import LearningCoachNodes
from learning_coach.resilience import (
    default_model_retry_policy,
    diagnostic_cache_key,
    node_cache_enabled,
)
from learning_coach.state import LearningState


def build_learning_graph(
    model: Any,
    *,
    checkpointer: Any | None = None,
    cache: Any | None = None,
    retry_policy: RetryPolicy | None = None,
    enable_node_cache: bool | None = None,
) -> Any:
    """Build the parallel learning workflow around the supplied model.

    ``teach`` is a bounded multi-agent swarm subgraph (orchestrator, research
    workers, teacher, review workers) running in parallel with the
    deterministic ``prepare_practice`` agent. Model nodes retry transient
    provider errors; the pure ``make_diagnostic`` node additionally caches its
    update per topic and diagnostic images.
    """

    nodes = LearningCoachNodes(model)
    retry = (
        retry_policy if retry_policy is not None else default_model_retry_policy()
    )
    cache_enabled = (
        node_cache_enabled(os.environ)
        if enable_node_cache is None
        else enable_node_cache
    )
    graph_cache = (
        cache
        if cache is not None
        else (InMemoryCache() if cache_enabled else None)
    )
    diagnostic_cache_policy = (
        CachePolicy(key_func=diagnostic_cache_key)
        if graph_cache is not None
        else None
    )
    teaching_swarm = build_teaching_swarm(
        nodes.runnables, retriever=resolve_teaching_retriever(nodes.runnables)
    )

    builder = StateGraph(
        LearningState, context_schema=LearningRuntimeContext
    )

    builder.add_node(
        "make_diagnostic",
        nodes.make_diagnostic,
        retry_policy=retry,
        cache_policy=diagnostic_cache_policy,
    )
    builder.add_node(
        "collect_diagnostic",
        nodes.collect_diagnostic,
        destinations=("teach", "prepare_practice"),
    )
    builder.add_node("teach", teaching_swarm, retry_policy=retry)
    builder.add_node("prepare_practice", nodes.prepare_practice)
    builder.add_node("make_quiz", nodes.make_quiz, retry_policy=retry)
    builder.add_node("collect_quiz", nodes.collect_quiz)
    builder.add_node(
        "assess",
        nodes.assess,
        retry_policy=retry,
        destinations=("teach", "prepare_practice", "summarize"),
    )
    builder.add_node("summarize", nodes.summarize, retry_policy=retry)

    builder.add_edge(START, "make_diagnostic")
    builder.add_edge("make_diagnostic", "collect_diagnostic")
    builder.add_edge("teach", "make_quiz")
    builder.add_edge("prepare_practice", "make_quiz")
    builder.add_edge("make_quiz", "collect_quiz")
    builder.add_edge("collect_quiz", "assess")
    builder.add_edge("summarize", END)

    return builder.compile(
        checkpointer=checkpointer or InMemorySaver(), cache=graph_cache
    )
