import argparse
import uuid
from collections.abc import Mapping
from typing import Any

from langgraph.types import Command

from learning_coach.graph import build_learning_graph
from learning_coach.model import create_chat_model


def _read_topic(argument: str | None) -> str:
    topic = (argument or input("你想学习什么主题？ ")).strip()
    if not topic:
        raise SystemExit("学习主题不能为空。")
    return topic


def _ask_for_answer(payload: Any) -> str:
    if isinstance(payload, Mapping):
        kind = payload.get("kind", "question")
        question = payload.get("question", payload)
    else:
        kind = "question"
        question = payload

    print(f"\n[{kind}] {question}")
    answer = input("你的回答：").strip()
    if not answer:
        print("回答为空也会继续，但评价结果可能没有参考价值。")
    return answer


def run(topic: str, *, thread_id: str | None = None) -> dict[str, Any]:
    """Run one learning session until the graph finishes."""

    graph = build_learning_graph(create_chat_model())
    config = {
        "configurable": {"thread_id": thread_id or f"learning-{uuid.uuid4().hex}"}
    }
    result = graph.invoke({"topic": topic, "attempts": 0}, config=config)

    while result.get("__interrupt__"):
        pending = result["__interrupt__"][0]
        answer = _ask_for_answer(pending.value)
        result = graph.invoke(Command(resume=answer), config=config)

    print("\n学习小结")
    print(result["summary"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="运行会诊断、讲解、出题和补救的 AI 学习教练。"
    )
    parser.add_argument("topic", nargs="?", help="本次要学习的主题")
    args = parser.parse_args()

    try:
        run(_read_topic(args.topic))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
