import argparse
import os
import sys
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.types import Command

from learning_coach.auth import run_auth_action
from learning_coach.context import (
    LearningContextSettings,
    create_learning_runtime_context,
)
from learning_coach.graph import build_learning_graph
from learning_coach.ingestion import (
    MaterialIngestionPipeline,
    material_inputs_from_sources,
)
from learning_coach.loaders import default_loader_registry
from learning_coach.media import image_content_block
from learning_coach.memory import create_checkpointer, create_memory_store
from learning_coach.model import create_model_suite
from learning_coach.state import learning_mode_for_new_session


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
    if kind == "approval":
        answer = input("批准执行？输入 approve 批准，其他任意输入拒绝：").strip()
        return answer or "reject"
    answer = input("你的回答：").strip()
    if not answer:
        print("回答为空也会继续，但评价结果可能没有参考价值。")
    return answer


def run(
    topic: str,
    *,
    thread_id: str | None = None,
    learner_id: str = "local-learner",
    image_sources: Sequence[str] = (),
    material_sources: Sequence[str] = (),
    learning_goal: str | None = None,
    learning_mode: str | None = None,
) -> dict[str, Any]:
    """Run one learning session until the graph finishes.

    With a durable ``CHECKPOINT_DB_PATH`` configured, passing the same
    ``thread_id`` resumes an interrupted session in a new process instead of
    starting over.
    """

    models = create_model_suite()
    images = [image_content_block(source) for source in image_sources]
    if images and not models.accepts_images:
        raise RuntimeError(
            "当前主模型的 profile 没有声明图片输入能力。"
            "请更换视觉模型，或为兼容端点设置 IMAGE_INPUT_POLICY=allow。"
        )

    ingestion = None
    if material_sources:
        materials = material_inputs_from_sources(material_sources)
        ingestion = MaterialIngestionPipeline(
            default_loader_registry(
                image_model=getattr(models, "chat", None),
                accepts_images=models.accepts_images,
            )
        ).ingest(materials)

    graph = build_learning_graph(
        models,
        checkpointer=create_checkpointer(os.environ),
        store=create_memory_store(os.environ),
    )
    runtime_context = create_learning_runtime_context(
        topic,
        learning_goal=learning_goal,
        settings=LearningContextSettings.from_environ(os.environ),
    )
    config = {
        "configurable": {"thread_id": thread_id or f"learning-{uuid.uuid4().hex}"}
    }
    existing = graph.get_state(config)
    resuming = bool(existing.values or existing.tasks)
    initial_state: dict[str, Any] = {
        "topic": topic,
        "learning_mode": learning_mode_for_new_session(learning_mode),
        "learning_goal": runtime_context.learning_goal,
        "learner_id": learner_id,
        "mastery_level": 0,
        "recent_errors": [],
        "attempts": 0,
    }
    if images:
        initial_state["diagnostic_images"] = images
    if ingestion is not None:
        initial_state["study_chunks"] = [
            chunk.model_dump() for chunk in ingestion.chunks
        ]
        initial_state["ingestion_report"] = ingestion.report.model_dump()
    if resuming:
        print("检测到未完成的持久会话，从检查点继续。")
        result = graph.invoke(None, config=config, context=runtime_context)
    else:
        result = graph.invoke(
            initial_state, config=config, context=runtime_context
        )

    while result.get("__interrupt__"):
        pending = result["__interrupt__"][0]
        answer = _ask_for_answer(pending.value)
        result = graph.invoke(
            Command(resume=answer), config=config, context=runtime_context
        )

    print("\n学习小结")
    print(result["summary"])
    stage_report = result.get("stage_report")
    if stage_report:
        print("\n阶段报告")
        print(stage_report.get("summary", ""))
        mastery = stage_report.get("mastery") or {}
        weak = [
            concept.get("name")
            for concept in mastery.get("concepts", [])
            if concept.get("band") == "weak"
        ]
        if weak:
            print(f"薄弱概念：{'、'.join(weak)}")
        for step in mastery.get("recommended_next", [])[:2]:
            print(f"下一步：{step}")
    return result


def _run_evaluate_cli() -> None:
    from learning_coach.evaluation import evaluate_retrieval

    report = evaluate_retrieval()
    print("Learning Coach 离线检索评估（评估集固定，零模型调用）")
    print(f"查询数 {len(report.cases)} · hit@3 {report.hit_rate:.2f} · MRR {report.mrr:.2f}")
    for case in report.cases:
        status = "命中" if case.hit else "未命中"
        rank = f"第 {round(1 / case.reciprocal_rank)} 位" if case.reciprocal_rank else "—"
        print(f"  [{status}] {case.case_id} · {case.query} · {rank}")


def _run_auth_cli(arguments: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m learning_coach auth",
        description="使用官方 CLI 管理模型登录会话。",
    )
    parser.add_argument("action", choices=("login", "status", "logout"))
    parser.add_argument("provider", choices=("codex", "claude", "gemini"))
    args = parser.parse_args(arguments)
    run_auth_action(args.provider, args.action)


def _run_web_cli(arguments: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m learning_coach web",
        description="启动本地 AI 学习教练 Web 页面。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--model", help="覆盖 CHAT_MODEL_ID")
    parser.add_argument("--assessment-model", help="覆盖 ASSESSMENT_MODEL_ID")
    parser.add_argument("--reload", action="store_true", help="开发时自动重载")
    args = parser.parse_args(arguments)
    if not 1 <= args.port <= 65535:
        raise SystemExit("端口必须在 1 到 65535 之间。")
    if args.model:
        os.environ["CHAT_MODEL_ID"] = args.model.strip()
    if args.assessment_model:
        os.environ["ASSESSMENT_MODEL_ID"] = args.assessment_model.strip()

    import uvicorn

    uvicorn.run(
        "learning_coach.web:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "auth":
        try:
            _run_auth_cli(arguments[1:])
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        return
    if arguments and arguments[0] == "web":
        _run_web_cli(arguments[1:])
        return
    if arguments and arguments[0] == "evaluate":
        _run_evaluate_cli()
        return

    parser = argparse.ArgumentParser(
        description="运行会诊断、讲解、出题和补救的 AI 学习教练。"
    )
    parser.add_argument("topic", nargs="?", help="本次要学习的主题")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="PATH_OR_URL",
        help="随诊断题发送的图片；可重复传入",
    )
    parser.add_argument(
        "--material",
        action="append",
        default=[],
        metavar="PATH_OR_URL",
        help="学习资料文件或网页 URL；可重复传入",
    )
    parser.add_argument(
        "--goal",
        help="本次学习目标；未填写时默认为掌握当前主题",
    )
    parser.add_argument(
        "--learning-mode",
        choices=("teach_first", "diagnose_first"),
        default="teach_first",
        help="学习流程；默认先讲解再检查理解",
    )
    parser.add_argument(
        "--thread-id",
        help="会话线程 ID；配置 CHECKPOINT_DB_PATH 后可用同一 ID 跨进程恢复",
    )
    parser.add_argument(
        "--learner",
        default="local-learner",
        help="学习者标识，用于跨会话长期记忆；默认 local-learner",
    )
    args = parser.parse_args(arguments)

    try:
        run(
            _read_topic(args.topic),
            thread_id=args.thread_id,
            learner_id=args.learner,
            image_sources=args.image,
            material_sources=args.material,
            learning_goal=args.goal,
            learning_mode=args.learning_mode,
        )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
