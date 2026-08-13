from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from learning_coach.nodes import LearningCoachNodes, route_after_assessment
from learning_coach.context import LearningRuntimeContext
from learning_coach.state import LearningState


def build_learning_graph(model: Any, *, checkpointer: Any | None = None) -> Any:
    """Build the first complete learning workflow around the supplied model."""

    nodes = LearningCoachNodes(model)
    builder = StateGraph(
        LearningState, context_schema=LearningRuntimeContext
    )

    builder.add_node("make_diagnostic", nodes.make_diagnostic)
    builder.add_node("collect_diagnostic", nodes.collect_diagnostic)
    builder.add_node("teach", nodes.teach)
    builder.add_node("make_quiz", nodes.make_quiz)
    builder.add_node("collect_quiz", nodes.collect_quiz)
    builder.add_node("assess", nodes.assess)
    builder.add_node("summarize", nodes.summarize)

    builder.add_edge(START, "make_diagnostic")
    builder.add_edge("make_diagnostic", "collect_diagnostic")
    builder.add_edge("collect_diagnostic", "teach")
    builder.add_edge("teach", "make_quiz")
    builder.add_edge("make_quiz", "collect_quiz")
    builder.add_edge("collect_quiz", "assess")
    builder.add_conditional_edges(
        "assess",
        route_after_assessment,
        {"retry": "teach", "finish": "summarize"},
    )
    builder.add_edge("summarize", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
