from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_MATERIAL_FILES = 10
MAX_SINGLE_MATERIAL_BYTES = 10 * 1024 * 1024
MAX_TOTAL_MATERIAL_BYTES = 30 * 1024 * 1024
MAX_EXTRACTED_CHARS = 250_000
MAX_WEB_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_MATERIALS = 3

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
