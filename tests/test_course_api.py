import json
from io import BytesIO
from typing import Any

import pytest
from ebooklib import epub
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from learning_coach.ingestion import (
    COURSE_MATERIAL_LIMITS,
    MaterialInput,
    validate_material_batch,
)
from learning_coach.model import LearningCoachModels
from learning_coach.schemas import Assessment, Diagnostic
from learning_coach.web import LearningSessionService, create_app


class FakeStructuredModel:
    def __init__(self, owner: "FakeChatModel", schema: type[Any]) -> None:
        self.owner = owner
        self.schema = schema

    def invoke(self, messages: Any) -> Diagnostic | Assessment:
        if self.schema is Diagnostic:
            return Diagnostic(
                question="StateGraph 的条件边负责什么？",
                focus="条件路由",
                difficulty="foundation",
            )
        return Assessment(
            score=next(self.owner.scores),
            feedback="路由方向正确，但还要说明状态依据。",
            missing_point="条件函数应读取结构化状态。",
        )


class FakeChatModel:
    def __init__(self) -> None:
        self.profile = {
            "structured_output": True,
            "tool_calling": True,
            "image_inputs": True,
        }
        self.scores = iter((86, 86))
        self.responses = iter(
            [
                "条件边根据状态选择下一节点。",
                "请说明 route_after_assessment 应返回什么。",
                "score 达到阈值时返回 summarize。",
            ]
        )

    def invoke(self, messages: Any) -> AIMessage:
        return AIMessage(content=next(self.responses))

    def with_structured_output(
        self, schema: type[Any], *, method: str
    ) -> FakeStructuredModel:
        return FakeStructuredModel(self, schema)


def _chapter_body(anchor: str) -> str:
    sentence = f"{anchor} 是理解状态图的关键概念，需要结合并行分支与 Reducer 一起掌握。"
    return "<p>" + "</p><p>".join([sentence * 8] * 3) + "</p>"


def _course_epub_bytes() -> bytes:
    book = epub.EpubBook()
    book.set_identifier("course-book")
    book.set_title("状态图教程")
    book.set_language("zh")
    chapters = [
        epub.EpubHtml(
            title=title, file_name=f"chapter-{index}.xhtml", lang="zh"
        )
        for index, title in enumerate(("第一章 状态", "第二章 条件边"), start=1)
    ]
    for chapter, (index, title) in zip(
        chapters, enumerate(("第一章 状态", "第二章 条件边"), start=1)
    ):
        chapter.content = f"<h1>{title}</h1>" + _chapter_body(title)
        book.add_item(chapter)
    book.spine = ["nav", *chapters]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    output = BytesIO()
    epub.write_epub(output, book)
    return output.getvalue()


def make_service() -> tuple[TestClient, LearningSessionService]:
    models = LearningCoachModels.from_models(FakeChatModel())
    service = LearningSessionService(
        models=models,
        chat_model_id="fake:coach",
        assessment_model_id="fake:assessment",
    )
    client = TestClient(
        create_app(service=service),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )
    return client, service


def _create_course(client: TestClient, learner: str = "ray") -> dict[str, Any]:
    response = client.post(
        "/api/courses",
        data={"learner_id": learner},
        files={"book": ("状态图教程.epub", _course_epub_bytes(), "application/epub+zip")},
    )
    assert response.status_code == 201
    return response.json()


def _sse_state(response: Any) -> dict[str, Any]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = "message"
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line.removeprefix("data: "))))
    assert events[-1][0] == "done"
    return next(payload for event, payload in events if event == "state")


def test_course_limits_accept_books_beyond_normal_material_size() -> None:
    relaxed = MaterialInput(
        "大书.epub",
        "application/epub+zip",
        data=b"x" * (11 * 1024 * 1024),
        limits=COURSE_MATERIAL_LIMITS,
    )
    validate_material_batch([relaxed], limits=relaxed.limits)

    with pytest.raises(ValueError, match="单个资料"):
        MaterialInput(
            "大书.epub", "application/epub+zip", data=b"x" * (11 * 1024 * 1024)
        )


def test_create_course_lists_and_details_chapters() -> None:
    client, _ = make_service()
    course = _create_course(client)

    assert course["book_title"] == "状态图教程"
    assert [chapter["chapter_id"] for chapter in course["chapters"]] == ["1", "2"]
    assert course["chapters"][0]["title"] == "第一章 状态"
    assert course["chapters"][0]["status"] == "not_started"
    assert course["next_chapter_id"] == "1"

    listed = client.get("/api/learners/ray/courses").json()
    assert [item["course_id"] for item in listed] == [course["course_id"]]
    assert listed[0]["completed_chapters"] == 0

    detail = client.get(
        "/api/courses/{0}".format(course["course_id"]),
        params={"learner_id": "ray"},
    ).json()
    assert [chapter["title"] for chapter in detail["chapters"]] == [
        "第一章 状态",
        "第二章 条件边",
    ]


def test_create_course_rejects_oversized_and_unparsable_books() -> None:
    client, _ = make_service()

    oversize = client.post(
        "/api/courses",
        data={"learner_id": "ray"},
        files={
            "book": (
                "huge.epub",
                b"x" * (COURSE_MATERIAL_LIMITS.max_single_bytes + 1),
                "application/epub+zip",
            )
        },
    )
    assert oversize.status_code == 422

    unparsable = client.post(
        "/api/courses",
        data={"learner_id": "ray"},
        files={"book": ("broken.epub", b"not an epub", "application/epub+zip")},
    )
    assert unparsable.status_code == 422
    assert "secret" not in json.dumps(unparsable.json())


def test_chapter_session_scopes_chunks_and_records_progress() -> None:
    client, service = make_service()
    course = _create_course(client)

    prepared = service._prepare_chapter_session(
        course["course_id"], "2", "ray", None
    )
    chunks = prepared["initial_state"]["study_chunks"]
    assert len(chunks) >= 2
    assert {chunk["chapter"] for chunk in chunks} == {"第二章 条件边"}

    started = client.post(
        "/api/courses/{0}/chapters/2/sessions/stream".format(
            course["course_id"]
        ),
        data={"learner_id": "ray", "learning_mode": "teach_first"},
    )
    assert started.status_code == 201
    state = _sse_state(started)
    assert state["status"] == "waiting"
    assert state["stage"] == "understanding_check"
    assert state["course"]["course_id"] == course["course_id"]
    assert state["course"]["chapter_title"] == "第二章 条件边"
    assert state["topic"].startswith("《状态图教程》第二章")

    detail = client.get(
        "/api/courses/{0}".format(course["course_id"]),
        params={"learner_id": "ray"},
    ).json()
    assert detail["chapters"][1]["status"] == "in_progress"

    session_id = state["session_id"]
    quizzed = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"answer": "它根据状态选择节点。"},
    ).json()
    assert quizzed["stage"] == "quiz"
    completed = client.post(
        f"/api/sessions/{session_id}/answers",
        json={"answer": "score 达到阈值时返回 summarize。"},
    ).json()
    assert completed["status"] == "completed"
    assert completed["course"]["chapter_id"] == "2"

    detail = client.get(
        "/api/courses/{0}".format(course["course_id"]),
        params={"learner_id": "ray"},
    ).json()
    assert detail["chapters"][1]["status"] == "completed"
    assert detail["chapters"][1]["score"] == 86
    assert detail["completed_chapters"] == 1
    assert detail["next_chapter_id"] == "1"


def test_course_corpus_survives_reupload_and_keeps_progress() -> None:
    client, service = make_service()
    course = _create_course(client)
    course_id = course["course_id"]

    service._course_corpora.clear()
    missing = client.post(
        f"/api/courses/{course_id}/chapters/1/sessions/stream",
        data={"learner_id": "ray"},
    )
    assert missing.status_code == 422
    assert "重新上传" in missing.json()["detail"]

    restored = _create_course(client)
    assert restored["course_id"] == course_id
    assert restored["chapters"][0]["status"] == "not_started"


def test_unknown_course_or_chapter_returns_404() -> None:
    client, _ = make_service()

    missing_course = client.get("/api/courses/{0}".format("f" * 64))
    assert missing_course.status_code == 404

    course = _create_course(client)
    missing_chapter = client.post(
        "/api/courses/{0}/chapters/9/sessions/stream".format(course["course_id"]),
        data={"learner_id": "ray"},
    )
    assert missing_chapter.status_code == 404
