"""Book-backed course outlines and cross-session chapter progress.

A course turns one uploaded book into an ordered chapter list built from the
material's real structure: EPUB chapters, DOCX/HTML headings, or deterministic
page/position windows when no structure exists. Chapter progress lives in the
same LangGraph store as learner memory (durable via ``MEMORY_DB_PATH``) while
the book text itself stays in process memory only.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from learning_coach.ingestion import StudyChunkRecord

COURSE_NAMESPACE = "course_progress"
COURSE_KEY_PREFIX = "course:"

MAX_COURSE_CHAPTERS = 60
MIN_CHAPTER_CHUNKS = 2
COURSE_PAGES_PER_SEGMENT = 12
COURSE_FALLBACK_GROUP_SIZE = 12

ChapterStatus = Literal["not_started", "in_progress", "completed"]


class CourseChapter(BaseModel):
    """One teachable unit of a course with a stable positional id."""

    chapter_id: str = Field(pattern=r"^[1-9][0-9]{0,3}$")
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=512)
    order: int = Field(ge=1)
    chunks: int = Field(ge=1)


class CourseOutline(BaseModel):
    """The deterministic outline derived from one book's chunks."""

    course_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    book_title: str = Field(min_length=1, max_length=200)
    chapters: list[CourseChapter] = Field(min_length=1)
    total_chunks: int = Field(ge=1)


class ChapterProgressRecord(BaseModel):
    status: ChapterStatus = "not_started"
    score: int | None = Field(default=None, ge=0, le=100)
    attempts: int = Field(default=0, ge=0)
    updated_at: str = Field(default="", max_length=40)


class CourseRecord(BaseModel):
    """The persisted course definition plus per-chapter progress."""

    course_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    book_title: str = Field(min_length=1, max_length=200)
    chapters: list[CourseChapter] = Field(min_length=1)
    progress: dict[str, ChapterProgressRecord] = Field(default_factory=dict)
    created_at: str = Field(default="", max_length=40)
    updated_at: str = Field(default="", max_length=40)


class _ChapterGroup:
    __slots__ = ("title", "location", "chunks")

    def __init__(self, title: str, location: str = "") -> None:
        self.title = title
        self.location = location
        self.chunks: list[StudyChunkRecord] = []


def _course_key(course_id: str) -> str:
    return f"{COURSE_KEY_PREFIX}{course_id}"


def _course_namespace(learner_id: str) -> tuple[str, str]:
    normalized = (learner_id or "").strip() or "local-learner"
    return (COURSE_NAMESPACE, normalized[:100])


def _segment_title(index: int) -> str:
    return f"第 {index + 1} 部分"


def _page_segment_title(
    index: int, first_page: int, last_page: int
) -> str:
    if first_page == last_page:
        return f"第 {index + 1} 讲（第 {first_page} 页）"
    return f"第 {index + 1} 讲（第 {first_page}–{last_page} 页）"


def _group_chunks(chunks: Sequence[StudyChunkRecord]) -> list[_ChapterGroup]:
    """Group chunks deterministically by real structure or fixed windows."""

    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    groups: list[_ChapterGroup] = []
    group_by_key: dict[str, _ChapterGroup] = {}
    position_segments: dict[str, int] = {}
    unstructured_seen = 0

    for chunk in ordered:
        if chunk.chapter:
            key = f"chapter\0{chunk.chapter}"
            title = chunk.chapter[:200]
            location = chunk.location[:512]
        elif chunk.heading:
            key = f"heading\0{chunk.heading}"
            title = chunk.heading[:200]
            location = chunk.location[:512]
        elif chunk.page is not None:
            segment = (chunk.page - 1) // COURSE_PAGES_PER_SEGMENT
            key = f"pages\0{segment}"
            title = ""
            location = ""
        else:
            segment = unstructured_seen // COURSE_FALLBACK_GROUP_SIZE
            unstructured_seen += 1
            key = f"position\0{segment}"
            title = ""
            location = ""
        group = group_by_key.get(key)
        if group is None:
            group = _ChapterGroup(title, location)
            group_by_key[key] = group
            groups.append(group)
            if key.startswith("position\0"):
                position_segments[key] = segment
        group.chunks.append(chunk)

    for group in groups:
        if group.title:
            continue
        pages = [chunk.page for chunk in group.chunks if chunk.page]
        if pages:
            segment = (min(pages) - 1) // COURSE_PAGES_PER_SEGMENT
            group.title = _page_segment_title(segment, min(pages), max(pages))
            group.location = f"pages {min(pages)}-{max(pages)}"
        else:
            group.title = ""
    for key, segment in position_segments.items():
        group = group_by_key[key]
        if not group.title:
            group.title = _segment_title(segment)
    return groups


def _merge_tiny_groups(groups: Sequence[_ChapterGroup]) -> list[_ChapterGroup]:
    """Fold chapters too small to teach into their predecessor."""

    merged: list[_ChapterGroup] = []
    pending: _ChapterGroup | None = None
    for group in groups:
        if len(group.chunks) < MIN_CHAPTER_CHUNKS:
            if merged:
                merged[-1].chunks.extend(group.chunks)
            elif pending is None:
                pending = group
            else:
                pending.chunks.extend(group.chunks)
            continue
        if pending is not None:
            group.chunks = [*pending.chunks, *group.chunks]
            pending = None
        merged.append(group)
    if pending is not None:
        if merged:
            merged[-1].chunks.extend(pending.chunks)
        else:
            merged.append(pending)
    return merged


def _cap_chapter_count(groups: Sequence[_ChapterGroup]) -> list[_ChapterGroup]:
    """Merge the smallest adjacent pair until the outline fits the cap."""

    merged = list(groups)
    while len(merged) > MAX_COURSE_CHAPTERS:
        smallest = 0
        smallest_size = len(merged[0].chunks) + len(merged[1].chunks)
        for index in range(1, len(merged) - 1):
            size = len(merged[index].chunks) + len(merged[index + 1].chunks)
            if size < smallest_size:
                smallest = index
                smallest_size = size
        merged[smallest].chunks.extend(merged[smallest + 1].chunks)
        del merged[smallest + 1]
    return merged


def build_course_outline(
    book_title: str, chunks: Sequence[StudyChunkRecord]
) -> CourseOutline:
    """Build a deterministic chapter outline from one book's chunks."""

    normalized_title = (book_title or "").strip() or "未命名资料"
    if not chunks:
        raise ValueError("资料没有提取出可学习的内容，无法创建课程。")
    source_ids = {chunk.source_id for chunk in chunks}
    if len(source_ids) != 1:
        raise ValueError("课程必须且只能基于一份资料创建。")
    groups = _cap_chapter_count(_merge_tiny_groups(_group_chunks(chunks)))
    chapters = [
        CourseChapter(
            chapter_id=str(index + 1),
            title=group.title or _segment_title(index),
            location=group.location,
            order=index + 1,
            chunks=len(group.chunks),
        )
        for index, group in enumerate(groups)
    ]
    return CourseOutline(
        course_id=chunks[0].content_hash,
        book_title=normalized_title[:200],
        chapters=chapters,
        total_chunks=len(chunks),
    )


def chapter_chunks(
    chunks: Sequence[StudyChunkRecord], chapter_id: str
) -> list[StudyChunkRecord]:
    """Return the chunks of one chapter using the same grouping rules."""

    groups = _cap_chapter_count(_merge_tiny_groups(_group_chunks(chunks)))
    index = int(chapter_id) - 1
    if index < 0 or index >= len(groups):
        raise LookupError("找不到指定的章节。")
    return list(groups[index].chunks)


def _record_from_item(value: Mapping[str, Any]) -> CourseRecord:
    return CourseRecord.model_validate(dict(value))


def save_course(
    store: Any, learner_id: str, outline: CourseOutline, *, now: str
) -> CourseRecord:
    """Create the course record; re-uploads keep existing chapter progress."""

    existing = load_course(store, learner_id, outline.course_id)
    if existing is not None:
        existing.chapters = outline.chapters
        existing.updated_at = now
        record = existing
    else:
        record = CourseRecord(
            course_id=outline.course_id,
            book_title=outline.book_title,
            chapters=outline.chapters,
            created_at=now,
            updated_at=now,
        )
    store.put(
        _course_namespace(learner_id),
        _course_key(outline.course_id),
        record.model_dump(mode="json"),
    )
    return record


def load_course(
    store: Any, learner_id: str, course_id: str
) -> CourseRecord | None:
    item = store.get(_course_namespace(learner_id), _course_key(course_id))
    return _record_from_item(item.value) if item is not None else None


def list_courses(store: Any, learner_id: str) -> list[CourseRecord]:
    items = store.search(_course_namespace(learner_id), limit=100)
    records = [
        _record_from_item(item.value)
        for item in items
        if item.key.startswith(COURSE_KEY_PREFIX)
    ]
    return sorted(records, key=lambda record: record.updated_at, reverse=True)


def record_chapter_result(
    store: Any,
    learner_id: str,
    course_id: str,
    chapter_id: str,
    *,
    status: ChapterStatus,
    score: int | None = None,
    attempts: int = 0,
    now: str = "",
) -> CourseRecord:
    """Overwrite one chapter's progress entry; the course key stays stable."""

    record = load_course(store, learner_id, course_id)
    if record is None:
        raise LookupError("找不到指定的课程。")
    if chapter_id not in {chapter.chapter_id for chapter in record.chapters}:
        raise LookupError("找不到指定的章节。")
    record.progress[chapter_id] = ChapterProgressRecord(
        status=status,
        score=score,
        attempts=attempts,
        updated_at=now,
    )
    record.updated_at = now
    store.put(
        _course_namespace(learner_id),
        _course_key(course_id),
        record.model_dump(mode="json"),
    )
    return record


def course_summary(record: CourseRecord) -> dict[str, Any]:
    """A bounded list-view projection: counts, average and the next chapter."""

    completed = [
        entry for entry in record.progress.values() if entry.status == "completed"
    ]
    next_chapter = next(
        (
            chapter
            for chapter in record.chapters
            if record.progress.get(chapter.chapter_id) is None
            or record.progress.get(chapter.chapter_id).status != "completed"
        ),
        None,
    )
    return {
        "course_id": record.course_id,
        "book_title": record.book_title,
        "chapters_total": len(record.chapters),
        "completed_chapters": len(completed),
        "average_score": (
            round(
                sum(entry.score or 0 for entry in completed) / len(completed)
            )
            if completed
            else None
        ),
        "next_chapter_id": next_chapter.chapter_id if next_chapter else None,
        "next_chapter_title": next_chapter.title if next_chapter else None,
        "updated_at": record.updated_at,
    }
