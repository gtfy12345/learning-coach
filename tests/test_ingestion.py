from pathlib import Path

import pytest
from langchain_core.documents import Document

from learning_coach.ingestion import (
    MAX_MATERIAL_FILES,
    MAX_SINGLE_MATERIAL_BYTES,
    MaterialInput,
    MaterialMetadata,
    validate_material_batch,
)
from learning_coach.loaders import MaterialLoaderRegistry


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
