from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from learning_coach.context import LearningRuntimeContext
from learning_coach.nodes import LearningCoachNodes
from learning_coach.state import LearningState


def build_learning_graph(model: Any, *, checkpointer: Any | None = None) -> Any:
    """Build the parallel learning workflow around the supplied model.

    ``teach`` (model-backed) and ``prepare_practice`` (deterministic) run in
    parallel after the diagnostic answer and merge at ``make_quiz``; the
    remediation loop re-enters the same parallel pair and stays bounded by
    ``route_after_assessment``.
    """

    nodes = LearningCoachNodes(model)
    builder = StateGraph(
        LearningState, context_schema=LearningRuntimeContext
    )

    builder.add_node("make_diagnostic", nodes.make_diagnostic)
    builder.add_node(
        "collect_diagnostic",
        nodes.collect_diagnostic,
        destinations=("teach", "prepare_practice"),
    )
    builder.add_node("teach", nodes.teach)
    builder.add_node("prepare_practice", nodes.prepare_practice)
    builder.add_node("make_quiz", nodes.make_quiz)
    builder.add_node("collect_quiz", nodes.collect_quiz)
    builder.add_node(
        "assess",
        nodes.assess,
        destinations=("teach", "prepare_practice", "summarize"),
    )
    builder.add_node("summarize", nodes.summarize)

    builder.add_edge(START, "make_diagnostic")
    builder.add_edge("make_diagnostic", "collect_diagnostic")
    builder.add_edge("teach", "make_quiz")
    builder.add_edge("prepare_practice", "make_quiz")
    builder.add_edge("make_quiz", "collect_quiz")
    builder.add_edge("collect_quiz", "assess")
    builder.add_edge("summarize", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
