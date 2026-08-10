import base64

import pytest

from learning_coach.media import image_bytes_content_block, image_content_block


def test_url_becomes_standard_image_block() -> None:
    assert image_content_block("https://example.com/diagram.png") == {
        "type": "image",
        "url": "https://example.com/diagram.png",
    }


def test_local_image_is_embedded_as_base64(tmp_path) -> None:
    path = tmp_path / "diagram.png"
    path.write_bytes(b"fake-png")

    block = image_content_block(str(path))

    assert block["type"] == "image"
    assert block["mime_type"] == "image/png"
    assert base64.b64decode(block["base64"]) == b"fake-png"


def test_unsupported_local_file_is_rejected(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not an image")

    with pytest.raises(ValueError, match="不支持的图片类型"):
        image_content_block(str(path))


def test_oversized_local_image_is_rejected(tmp_path) -> None:
    path = tmp_path / "large.png"
    path.write_bytes(b"1234")

    with pytest.raises(ValueError, match="不能超过 3 字节"):
        image_content_block(str(path), max_bytes=3)


def test_uploaded_image_bytes_become_a_standard_content_block() -> None:
    block = image_bytes_content_block(b"image", "image/png")

    assert block["type"] == "image"
    assert block["mime_type"] == "image/png"
    assert block["base64"] == "aW1hZ2U="


def test_uploaded_image_rejects_unsupported_content_type() -> None:
    with pytest.raises(ValueError, match="不支持的图片类型"):
        image_bytes_content_block(b"image", "image/svg+xml")
