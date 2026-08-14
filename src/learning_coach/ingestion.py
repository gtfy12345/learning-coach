from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field, field_validator, model_validator

MAX_MATERIAL_FILES = 10
MAX_SINGLE_MATERIAL_BYTES = 10 * 1024 * 1024
MAX_TOTAL_MATERIAL_BYTES = 30 * 1024 * 1024
MAX_EXTRACTED_CHARS = 250_000
MAX_WEB_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_MATERIALS = 3
DEFAULT_MATERIAL_CHUNK_SIZE = 1_000
DEFAULT_MATERIAL_CHUNK_OVERLAP = 150

MaterialSourceType = Literal[
    "pdf",
    "docx",
    "pptx",
    "epub",
    "html",
    "text",
    "code",
    "web",
    "image",
]


@dataclass(frozen=True)
class MaterialInput:
    """One bounded local upload or remote webpage to ingest."""

    source_name: str
    mime_type: str
    data: bytes | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        normalized_name = Path(self.source_name.strip()).name
        normalized_type = self.mime_type.strip().lower()
        normalized_url = (self.source_url or "").strip() or None
        has_data = self.data is not None
        has_url = normalized_url is not None
        if has_data == has_url:
            raise ValueError("资料必须且只能提供文件内容或网页 URL。")
        if not normalized_name:
            raise ValueError("资料名称不能为空。")
        if has_data:
            assert self.data is not None
            if not self.data:
                raise ValueError("资料内容不能为空。")
            if len(self.data) > MAX_SINGLE_MATERIAL_BYTES:
                raise ValueError(
                    f"单个资料不能超过 {MAX_SINGLE_MATERIAL_BYTES} 字节。"
                )
        object.__setattr__(self, "source_name", normalized_name)
        object.__setattr__(self, "mime_type", normalized_type)
        object.__setattr__(self, "source_url", normalized_url)

    @property
    def source_uri(self) -> str:
        return self.source_url or self.source_name

    @property
    def suffix(self) -> str:
        path = urlparse(self.source_url).path if self.source_url else self.source_name
        return Path(path).suffix.casefold()

    @property
    def byte_size(self) -> int:
        return len(self.data or b"")


class MaterialMetadata(BaseModel):
    """Validated metadata shared by every loaded document and chunk."""

    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_key: str = Field(min_length=1, max_length=2048)
    source_type: MaterialSourceType
    source_name: str = Field(min_length=1, max_length=512)
    source_uri: str = Field(min_length=1, max_length=4096)
    mime_type: str = Field(min_length=1, max_length=255)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    location_type: str = Field(min_length=1, max_length=64)
    location: str = Field(min_length=1, max_length=512)
    page: int | None = Field(default=None, ge=1)
    slide: int | None = Field(default=None, ge=1)
    chapter: str | None = Field(default=None, max_length=512)
    heading: str | None = Field(default=None, max_length=512)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)

    @field_validator("source_uri")
    @classmethod
    def reject_absolute_local_paths(cls, value: str) -> str:
        parsed = urlparse(value)
        if not parsed.scheme and Path(value).is_absolute():
            raise ValueError("source_uri 不能包含服务器绝对路径。")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> "MaterialMetadata":
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end 不能小于 line_start。")
        return self


class IngestionError(BaseModel):
    source_name: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)


class IngestedSource(BaseModel):
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_name: str = Field(min_length=1, max_length=512)
    source_type: MaterialSourceType
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunks: int = Field(ge=0)
    status: Literal["added", "updated", "skipped", "deleted"]


class IngestionReport(BaseModel):
    sources_received: int = Field(default=0, ge=0)
    sources_added: int = Field(default=0, ge=0)
    sources_updated: int = Field(default=0, ge=0)
    sources_skipped: int = Field(default=0, ge=0)
    sources_deleted: int = Field(default=0, ge=0)
    chunks_added: int = Field(default=0, ge=0)
    chunks_deleted: int = Field(default=0, ge=0)
    sources: list[IngestedSource] = Field(default_factory=list)
    errors: list[IngestionError] = Field(default_factory=list)


class StudyChunkRecord(MaterialMetadata):
    """Serializable location-aware chunk stored in LangGraph state."""

    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_index: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    text: str = Field(min_length=1)
    paragraph: int | None = Field(default=None, ge=1)
    language: str | None = Field(default=None, max_length=64)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_character_range(self) -> "StudyChunkRecord":
        if self.char_end <= self.char_start:
            raise ValueError("char_end 必须大于 char_start。")
        return self


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocationAwareSplitter:
    """Split within loader-defined locations and retain stable provenance."""

    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_MATERIAL_CHUNK_SIZE,
        overlap: int = DEFAULT_MATERIAL_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须是正整数。")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap 必须大于等于 0 且小于 chunk_size。")
        self._chunk_size = chunk_size
        self._overlap = overlap

    def split_documents(
        self, documents: Sequence[Document]
    ) -> list[StudyChunkRecord]:
        chunks: list[StudyChunkRecord] = []
        source_indexes: dict[str, int] = {}
        for document in documents:
            base = MaterialMetadata.model_validate(document.metadata)
            if not document.page_content.strip():
                continue
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self._chunk_size,
                chunk_overlap=self._overlap,
                add_start_index=True,
                keep_separator=True,
                separators=(
                    ["\n\n", "\n", " ", ""]
                    if base.source_type == "code"
                    else ["\n\n", "\n", "。", "！", "？", ". ", " ", ""]
                ),
            )
            for split in splitter.split_documents([document]):
                text = split.page_content.strip()
                if not text:
                    continue
                start = max(0, int(split.metadata.get("start_index", 0)))
                end = start + len(text)
                source_indexes[base.source_id] = source_indexes.get(base.source_id, 0) + 1
                chunk_index = source_indexes[base.source_id]
                metadata = dict(document.metadata)
                location = base.location
                if base.source_type == "code":
                    original_line = base.line_start or 1
                    line_start = original_line + document.page_content[:start].count("\n")
                    line_end = line_start + max(0, len(text.splitlines()) - 1)
                    metadata["line_start"] = line_start
                    metadata["line_end"] = line_end
                    location = f"lines {line_start}-{line_end}"
                metadata["location"] = location
                chunk_hash = _digest(
                    "\0".join(
                        [
                            base.source_id,
                            location,
                            " ".join(text.split()),
                        ]
                    )
                )
                chunk_id = _digest(
                    "\0".join(
                        [base.source_id, location, str(chunk_index), chunk_hash]
                    )
                )
                chunks.append(
                    StudyChunkRecord(
                        **{
                            key: value
                            for key, value in metadata.items()
                            if key != "start_index"
                        },
                        chunk_id=chunk_id,
                        chunk_hash=chunk_hash,
                        chunk_index=chunk_index,
                        char_start=start,
                        char_end=end,
                        text=text,
                    )
                )
        return chunks


def split_material_documents(
    documents: Sequence[Document],
    *,
    chunk_size: int = DEFAULT_MATERIAL_CHUNK_SIZE,
    overlap: int = DEFAULT_MATERIAL_CHUNK_OVERLAP,
) -> list[StudyChunkRecord]:
    return LocationAwareSplitter(
        chunk_size=chunk_size,
        overlap=overlap,
    ).split_documents(documents)


class InMemoryStudyIndex:
    """Session-scoped source index with deterministic incremental sync."""

    def __init__(self, *, splitter: LocationAwareSplitter | None = None) -> None:
        self._splitter = splitter or LocationAwareSplitter()
        self._content_hashes: dict[str, str] = {}
        self._chunks_by_source: dict[str, list[StudyChunkRecord]] = {}

    @property
    def chunks(self) -> list[StudyChunkRecord]:
        return [
            chunk
            for source_chunks in self._chunks_by_source.values()
            for chunk in source_chunks
        ]

    def sync(
        self,
        documents: Sequence[Document],
        *,
        cleanup: Literal["incremental", "full"] = "incremental",
    ) -> IngestionReport:
        if cleanup not in {"incremental", "full"}:
            raise ValueError("cleanup 必须是 incremental 或 full。")
        grouped: dict[str, list[Document]] = {}
        group_metadata: dict[str, MaterialMetadata] = {}
        for document in documents:
            metadata = MaterialMetadata.model_validate(document.metadata)
            existing = group_metadata.get(metadata.source_key)
            if existing is not None and existing.content_hash != metadata.content_hash:
                raise ValueError(
                    f"同一来源 {metadata.source_name} 包含不一致的 content_hash。"
                )
            group_metadata[metadata.source_key] = metadata
            grouped.setdefault(metadata.source_key, []).append(document)

        report = IngestionReport(sources_received=len(grouped))
        incoming_keys = set(grouped)
        for source_key, source_documents in grouped.items():
            metadata = group_metadata[source_key]
            current_hash = self._content_hashes.get(source_key)
            if current_hash == metadata.content_hash:
                current_chunks = self._chunks_by_source[source_key]
                report.sources_skipped += 1
                report.sources.append(
                    _source_summary(metadata, "skipped", len(current_chunks))
                )
                continue

            split = self._splitter.split_documents(source_documents)
            unique: list[StudyChunkRecord] = []
            seen_hashes: set[str] = set()
            for chunk in split:
                if chunk.chunk_hash in seen_hashes:
                    continue
                seen_hashes.add(chunk.chunk_hash)
                unique.append(chunk)
            if not unique:
                raise ValueError(f"资料没有可索引内容：{metadata.source_name}")

            old_chunks = self._chunks_by_source.get(source_key, [])
            if old_chunks:
                report.sources_updated += 1
                report.chunks_deleted += len(old_chunks)
                status: Literal["added", "updated", "skipped", "deleted"] = "updated"
            else:
                report.sources_added += 1
                status = "added"
            self._content_hashes[source_key] = metadata.content_hash
            self._chunks_by_source[source_key] = unique
            report.chunks_added += len(unique)
            report.sources.append(_source_summary(metadata, status, len(unique)))

        if cleanup == "full":
            for source_key in list(self._chunks_by_source):
                if source_key in incoming_keys:
                    continue
                old_chunks = self._chunks_by_source.pop(source_key)
                old_metadata = MaterialMetadata.model_validate(
                    old_chunks[0].model_dump()
                )
                self._content_hashes.pop(source_key, None)
                report.sources_deleted += 1
                report.chunks_deleted += len(old_chunks)
                report.sources.append(
                    _source_summary(old_metadata, "deleted", len(old_chunks))
                )
        return report


def _source_summary(
    metadata: MaterialMetadata,
    status: Literal["added", "updated", "skipped", "deleted"],
    chunks: int,
) -> IngestedSource:
    return IngestedSource(
        source_id=metadata.source_id,
        source_name=metadata.source_name,
        source_type=metadata.source_type,
        content_hash=metadata.content_hash,
        chunks=chunks,
        status=status,
    )


def validate_material_batch(materials: Sequence[MaterialInput]) -> None:
    """Enforce bounded ingestion before any parser or model is called."""

    if len(materials) > MAX_MATERIAL_FILES:
        raise ValueError(f"资料数量不能超过 {MAX_MATERIAL_FILES} 个。")
    total_bytes = sum(material.byte_size for material in materials)
    if total_bytes > MAX_TOTAL_MATERIAL_BYTES:
        raise ValueError(
            f"资料总大小不能超过 {MAX_TOTAL_MATERIAL_BYTES} 字节。"
        )
    image_count = sum(
        material.mime_type.startswith("image/") for material in materials
    )
    if image_count > MAX_IMAGE_MATERIALS:
        raise ValueError(f"图片资料不能超过 {MAX_IMAGE_MATERIALS} 张。")
