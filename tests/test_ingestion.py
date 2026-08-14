from pathlib import Path

import pytest
from langchain_core.documents import Document

from learning_coach.ingestion import (
    MAX_MATERIAL_FILES,
    MAX_SINGLE_MATERIAL_BYTES,
    InMemoryStudyIndex,
    LocationAwareSplitter,
    MaterialInput,
    MaterialMetadata,
    split_material_documents,
    validate_material_batch,
)
from learning_coach.loaders import MaterialLoaderRegistry, default_loader_registry


class _FakeLoader:
    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        self.loaded: list[MaterialInput] = []

    def supports(self, material: MaterialInput) -> bool:
        return material.suffix == self.suffix

    def load(self, material: MaterialInput) -> list[Document]:
        self.loaded.append(material)
        return [Document(page_content="loaded", metadata={"source_name": material.source_name})]


def test_material_input_requires_exactly_one_payload_and_sanitizes_name() -> None:
    local = MaterialInput(
        source_name="/private/course/../lesson.md",
        mime_type="text/markdown",
        data=b"# Reducer",
    )

    assert local.source_name == "lesson.md"
    assert local.source_uri == "lesson.md"
    assert local.suffix == ".md"

    remote = MaterialInput(
        source_name="notes",
        mime_type="text/html",
        source_url="https://example.com/course/intro",
    )
    assert remote.source_uri == "https://example.com/course/intro"

    windows_local = MaterialInput(
        source_name=r"C:\private\course\lesson.py",
        mime_type="text/x-python",
        data=b"print('safe')",
    )
    assert windows_local.source_name == "lesson.py"
    assert windows_local.source_uri == "lesson.py"

    with pytest.raises(ValueError, match="必须且只能提供"):
        MaterialInput(source_name="empty.txt", mime_type="text/plain")
    with pytest.raises(ValueError, match="必须且只能提供"):
        MaterialInput(
            source_name="both.txt",
            mime_type="text/plain",
            data=b"text",
            source_url="https://example.com/both",
        )
    with pytest.raises(ValueError, match="不能为空"):
        MaterialInput(source_name="empty.txt", mime_type="text/plain", data=b"")


def test_material_batch_enforces_file_count_single_and_total_byte_limits() -> None:
    materials = [
        MaterialInput(
            source_name=f"lesson-{index}.txt",
            mime_type="text/plain",
            data=b"a",
        )
        for index in range(MAX_MATERIAL_FILES)
    ]
    validate_material_batch(materials)

    with pytest.raises(ValueError, match="资料数量"):
        validate_material_batch(materials + [materials[0]])

    with pytest.raises(ValueError, match="单个资料"):
        MaterialInput(
            source_name="huge.txt",
            mime_type="text/plain",
            data=b"x" * (MAX_SINGLE_MATERIAL_BYTES + 1),
        )


def test_material_metadata_rejects_server_absolute_path() -> None:
    valid = MaterialMetadata(
        source_id="a" * 64,
        source_key="upload:lesson.py",
        source_type="code",
        source_name="lesson.py",
        source_uri="lesson.py",
        mime_type="text/x-python",
        content_hash="b" * 64,
        location_type="lines",
        location="lines 1-4",
        line_start=1,
        line_end=4,
    )
    assert valid.line_end == 4

    with pytest.raises(ValueError, match="绝对路径"):
        MaterialMetadata(
            source_id="a" * 64,
            source_key="upload:secret.py",
            source_type="code",
            source_name="secret.py",
            source_uri=str(Path("/private/tmp/secret.py")),
            mime_type="text/x-python",
            content_hash="b" * 64,
            location_type="lines",
            location="lines 1-1",
        )

    with pytest.raises(ValueError, match="http 或 https"):
        MaterialMetadata(
            source_id="a" * 64,
            source_key="upload:secret.py",
            source_type="code",
            source_name="secret.py",
            source_uri="file:///private/tmp/secret.py",
            mime_type="text/x-python",
            content_hash="b" * 64,
            location_type="lines",
            location="lines 1-1",
        )


def test_loader_registry_dispatches_supported_material_and_rejects_unknown() -> None:
    markdown = _FakeLoader(".md")
    registry = MaterialLoaderRegistry([markdown])
    material = MaterialInput(
        source_name="lesson.md",
        mime_type="text/markdown",
        data=b"# Lesson",
    )

    documents = registry.load(material)

    assert documents[0].page_content == "loaded"
    assert markdown.loaded == [material]

    with pytest.raises(ValueError, match="不支持的资料格式"):
        registry.load(
            MaterialInput(
                source_name="archive.zip",
                mime_type="application/zip",
                data=b"PK",
            )
        )


def test_location_aware_splitter_is_bounded_stable_and_preserves_page() -> None:
    material = MaterialInput(
        "paper.pdf",
        "application/pdf",
        data=(
            b"%PDF placeholder"
        ),
    )
    metadata = MaterialMetadata(
        source_id="a" * 64,
        source_key="upload:paper.pdf",
        source_type="pdf",
        source_name=material.source_name,
        source_uri=material.source_uri,
        mime_type=material.mime_type,
        content_hash="b" * 64,
        location_type="page",
        location="page 3",
        page=3,
    ).model_dump(exclude_none=True)
    document = Document(
        page_content=(
            "Reducer 负责合并并行状态。\n\n"
            "条件边根据结构化评分选择 retry 或 finish。\n\n"
            "所有补救循环都必须有明确终止条件。"
        ),
        metadata=metadata,
    )

    first = split_material_documents([document], chunk_size=38, overlap=6)
    second = split_material_documents([document], chunk_size=38, overlap=6)

    assert first == second
    assert len(first) >= 2
    assert all(len(chunk.text) <= 38 for chunk in first)
    assert all(chunk.page == 3 for chunk in first)
    assert [chunk.chunk_index for chunk in first] == list(range(1, len(first) + 1))
    assert all(len(chunk.chunk_id) == 64 for chunk in first)
    assert all(len(chunk.chunk_hash) == 64 for chunk in first)
    assert all(chunk.char_end > chunk.char_start >= 0 for chunk in first)


def test_code_splitter_updates_line_ranges_for_each_chunk() -> None:
    document = default_loader_registry().load(
        MaterialInput(
            "graph.py",
            "text/x-python",
            data=(
                "def diagnose():\n    return 'question'\n\n"
                "def teach():\n    return 'explanation'\n\n"
                "def route(score):\n    return 'finish' if score >= 80 else 'retry'\n"
            ).encode(),
        )
    )[0]

    chunks = LocationAwareSplitter(chunk_size=45, overlap=5).split_documents([document])

    assert len(chunks) >= 2
    assert chunks[0].line_start == 1
    assert chunks[-1].line_end == 8
    assert all(chunk.location == f"lines {chunk.line_start}-{chunk.line_end}" for chunk in chunks)
    assert all(chunk.language == "python" for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "message"),
    [(0, 0, "chunk_size"), (10, -1, "overlap"), (10, 10, "overlap")],
)
def test_location_splitter_rejects_invalid_bounds(
    chunk_size: int, overlap: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        LocationAwareSplitter(chunk_size=chunk_size, overlap=overlap)


def _text_documents(name: str, text: str) -> list[Document]:
    return default_loader_registry().load(
        MaterialInput(name, "text/plain", data=text.encode())
    )


def test_incremental_index_add_skip_update_and_remove_sources() -> None:
    index = InMemoryStudyIndex(
        splitter=LocationAwareSplitter(chunk_size=45, overlap=5)
    )
    first_documents = _text_documents(
        "lesson.txt",
        "Reducer 合并旧状态。\n\n条件边决定 retry 或 finish。",
    )

    added = index.sync(first_documents)
    unchanged = index.sync(first_documents)

    assert added.sources_received == 1
    assert added.sources_added == 1
    assert added.chunks_added == len(index.chunks)
    assert len(added.sources[0].content_hash) == 12
    assert unchanged.sources_skipped == 1
    assert unchanged.chunks_added == 0
    assert unchanged.chunks_deleted == 0

    old_hashes = {chunk.chunk_hash for chunk in index.chunks}
    updated = index.sync(
        _text_documents(
            "lesson.txt",
            "Reducer 合并新状态，并要求所有补救循环都有终止条件。",
        )
    )

    assert updated.sources_updated == 1
    assert updated.chunks_deleted == len(old_hashes)
    assert not old_hashes.intersection(chunk.chunk_hash for chunk in index.chunks)
    assert all("旧状态" not in chunk.text for chunk in index.chunks)

    second_documents = _text_documents(
        "quiz.txt",
        "练习题要求解释 Command 如何恢复 interrupt。",
    )
    appended = index.sync(second_documents)
    assert appended.sources_added == 1
    assert {chunk.source_name for chunk in index.chunks} == {
        "lesson.txt",
        "quiz.txt",
    }

    cleaned = index.sync(second_documents, cleanup="full")
    assert cleaned.sources_skipped == 1
    assert cleaned.sources_deleted == 1
    assert {chunk.source_name for chunk in index.chunks} == {"quiz.txt"}


def test_incremental_index_deduplicates_chunk_hashes_and_validates_cleanup() -> None:
    index = InMemoryStudyIndex()
    document = _text_documents("duplicate.txt", "完全相同的段落。")
    duplicated_units = [document[0], document[0].model_copy(deep=True)]

    report = index.sync(duplicated_units)

    assert report.sources_received == 1
    assert len(index.chunks) == 1
    with pytest.raises(ValueError, match="cleanup"):
        index.sync(document, cleanup="unknown")  # type: ignore[arg-type]


def test_public_docs_describe_multimodal_ingestion_and_dependencies() -> None:
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")

    for term in (
        "多模态学习资料摄取",
        "PDF",
        "DOCX",
        "PPTX",
        "EPUB",
        "source_urls",
        "--material",
        "LocationAwareSplitter",
        "content_hash",
        "chunk_hash",
        "增量索引",
        "SSRF",
        "不写入磁盘",
    ):
        assert term in readme
    for package in (
        "pypdf",
        "python-docx",
        "python-pptx",
        "EbookLib",
        "beautifulsoup4",
        "Pillow",
        "langchain-text-splitters",
    ):
        assert package in requirements
