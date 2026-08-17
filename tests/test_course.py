import hashlib

import pytest
from langgraph.store.memory import InMemoryStore

from learning_coach.course import (
    build_course_outline,
    chapter_chunks,
    course_summary,
    list_courses,
    load_course,
    record_chapter_result,
    save_course,
)
from learning_coach.ingestion import StudyChunkRecord

SOURCE_ID = "b" * 64
CONTENT_HASH = "c" * 64


def make_chunk(
    index: int,
    *,
    chapter: str | None = None,
    heading: str | None = None,
    page: int | None = None,
    source_type: str = "epub",
    source_id: str = SOURCE_ID,
    text: str = "一段可学习的正文内容。",
) -> StudyChunkRecord:
    if chapter:
        location_type, location = "chapter", f"chapter {chapter}"
    elif heading:
        location_type, location = "paragraph", heading
    elif page:
        location_type, location = "page", f"page {page}"
    else:
        location_type, location = "document", "document 1"
    return StudyChunkRecord(
        source_id=source_id,
        source_key=f"upload:book.{source_type}",
        source_type=source_type,
        source_name=f"book.{source_type}",
        source_uri=f"book.{source_type}",
        mime_type="application/octet-stream",
        content_hash=CONTENT_HASH,
        location_type=location_type,
        location=location,
        chunk_id=hashlib.sha256(f"chunk-{index}".encode()).hexdigest(),
        chunk_hash=hashlib.sha256(f"hash-{index}".encode()).hexdigest(),
        chunk_index=index,
        char_start=index * 100,
        char_end=index * 100 + 50,
        text=text,
        chapter=chapter,
        heading=heading,
        page=page,
    )


def epub_chunks() -> list[StudyChunkRecord]:
    return [
        make_chunk(1, chapter="第一章 引言"),
        make_chunk(2, chapter="第一章 引言"),
        make_chunk(3, chapter="第一章 引言"),
        make_chunk(4, chapter="第二章 基础"),
        make_chunk(5, chapter="第二章 基础"),
        make_chunk(6, chapter="第二章 基础"),
    ]


def test_build_course_outline_groups_epub_chapters() -> None:
    outline = build_course_outline("深入理解 LangGraph.epub", epub_chunks())

    assert outline.course_id == CONTENT_HASH
    assert outline.book_title == "深入理解 LangGraph.epub"
    assert outline.total_chunks == 6
    assert [chapter.chapter_id for chapter in outline.chapters] == ["1", "2"]
    assert [chapter.title for chapter in outline.chapters] == [
        "第一章 引言",
        "第二章 基础",
    ]
    assert [chapter.chunks for chapter in outline.chapters] == [3, 3]


def test_build_course_outline_groups_docx_headings_and_merges_tiny_groups() -> None:
    chunks = [
        make_chunk(1, heading="安装准备", source_type="docx"),
        make_chunk(2, heading="安装准备", source_type="docx"),
        make_chunk(3, heading="安装准备", source_type="docx"),
        make_chunk(4, heading="过渡小节", source_type="docx"),
        make_chunk(5, heading="配置详解", source_type="docx"),
        make_chunk(6, heading="配置详解", source_type="docx"),
    ]

    outline = build_course_outline("指南.docx", chunks)

    assert [chapter.title for chapter in outline.chapters] == [
        "安装准备",
        "配置详解",
    ]
    assert [chapter.chunks for chapter in outline.chapters] == [4, 2]


def test_build_course_outline_pdf_pages_fallback_segments() -> None:
    chunks = [
        make_chunk(index, page=page, source_type="pdf")
        for page in range(1, 31)
        for index in ((page - 1) * 2 + 1, (page - 1) * 2 + 2)
    ]

    outline = build_course_outline("机器学习.pdf", chunks)

    assert [chapter.title for chapter in outline.chapters] == [
        "第 1 讲（第 1–12 页）",
        "第 2 讲（第 13–24 页）",
        "第 3 讲（第 25–30 页）",
    ]
    assert [chapter.location for chapter in outline.chapters] == [
        "pages 1-12",
        "pages 13-24",
        "pages 25-30",
    ]
    assert [chapter.chunks for chapter in outline.chapters] == [24, 24, 12]


def test_build_course_outline_unstructured_text_fallback_parts() -> None:
    chunks = [make_chunk(index, source_type="text") for index in range(1, 31)]

    outline = build_course_outline("笔记.txt", chunks)

    assert [chapter.title for chapter in outline.chapters] == [
        "第 1 部分",
        "第 2 部分",
        "第 3 部分",
    ]
    assert [chapter.chunks for chapter in outline.chapters] == [12, 12, 6]


def test_build_course_outline_caps_chapter_count_and_keeps_chunks() -> None:
    chunks = [
        make_chunk(index, chapter=f"第 {chapter} 章")
        for chapter in range(1, 81)
        for index in ((chapter - 1) * 2 + 1, (chapter - 1) * 2 + 2)
    ]

    outline = build_course_outline("大部头.epub", chunks)

    assert len(outline.chapters) <= 60
    assert outline.total_chunks == 160
    assert sum(chapter.chunks for chapter in outline.chapters) == 160


def test_build_course_outline_rejects_empty_and_multi_source() -> None:
    with pytest.raises(ValueError, match="没有提取出"):
        build_course_outline("空资料.epub", [])
    mixed = [
        *epub_chunks()[:2],
        make_chunk(99, source_id="d" * 64, chapter="别的书"),
    ]
    with pytest.raises(ValueError, match="一份资料"):
        build_course_outline("混装.epub", mixed)


def test_chapter_chunks_returns_only_target_chapter() -> None:
    chunks = epub_chunks()

    second = chapter_chunks(chunks, "2")

    assert [chunk.chunk_index for chunk in second] == [4, 5, 6]
    with pytest.raises(LookupError):
        chapter_chunks(chunks, "9")


def test_course_progress_roundtrip_and_summary() -> None:
    store = InMemoryStore()
    outline = build_course_outline("深入理解 LangGraph.epub", epub_chunks())

    saved = save_course(store, "ray", outline, now="2026-08-17T10:00:00+00:00")
    assert saved.chapters == outline.chapters
    assert load_course(store, "ray", outline.course_id) is not None

    record_chapter_result(
        store,
        "ray",
        outline.course_id,
        "1",
        status="completed",
        score=85,
        attempts=1,
        now="2026-08-17T11:00:00+00:00",
    )
    resaved = save_course(
        store, "ray", outline, now="2026-08-17T12:00:00+00:00"
    )
    summary = course_summary(resaved)

    assert resaved.progress["1"].status == "completed"
    assert resaved.progress["1"].score == 85
    assert summary["completed_chapters"] == 1
    assert summary["average_score"] == 85
    assert summary["next_chapter_id"] == "2"
    assert summary["next_chapter_title"] == "第二章 基础"

    assert len(list_courses(store, "ray")) == 1


def test_course_progress_rejects_unknown_course_or_chapter() -> None:
    store = InMemoryStore()
    outline = build_course_outline("深入理解 LangGraph.epub", epub_chunks())
    save_course(store, "ray", outline, now="2026-08-17T10:00:00+00:00")

    with pytest.raises(LookupError, match="课程"):
        record_chapter_result(
            store, "ray", "f" * 64, "1", status="completed", now="x"
        )
    with pytest.raises(LookupError, match="章节"):
        record_chapter_result(
            store,
            "ray",
            outline.course_id,
            "9",
            status="completed",
            now="x",
        )
