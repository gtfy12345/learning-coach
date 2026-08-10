import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

MAX_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def image_bytes_content_block(
    image_bytes: bytes,
    mime_type: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> dict[str, str]:
    """Convert uploaded image bytes into a standard LangChain content block."""

    normalized_type = mime_type.strip().lower()
    if normalized_type not in SUPPORTED_IMAGE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES))
        raise ValueError(f"不支持的图片类型；当前支持：{supported}。")
    if not image_bytes:
        raise ValueError("上传的图片不能为空。")
    if len(image_bytes) > max_bytes:
        raise ValueError(f"图片不能超过 {max_bytes} 字节。")
    return {
        "type": "image",
        "base64": base64.b64encode(image_bytes).decode("ascii"),
        "mime_type": normalized_type,
    }


def image_content_block(
    source: str,
    *,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> dict[str, str]:
    """Convert an image URL or local file into a standard LangChain content block."""

    value = source.strip()
    if not value:
        raise ValueError("图片路径或 URL 不能为空。")

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return {"type": "image", "url": value}
    if parsed.scheme:
        raise ValueError("图片只支持本地文件、http URL 或 https URL。")

    path = Path(value).expanduser()
    if not path.is_file():
        raise ValueError(f"找不到图片文件：{path}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in SUPPORTED_IMAGE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES))
        raise ValueError(f"不支持的图片类型；当前支持：{supported}。")

    image_bytes = path.read_bytes()
    if len(image_bytes) > max_bytes:
        raise ValueError(f"图片不能超过 {max_bytes} 字节。")

    return image_bytes_content_block(image_bytes, mime_type, max_bytes=max_bytes)
