import base64
import json
import subprocess
from pathlib import Path

import pytest

from learning_coach.cli_models import create_cli_chat_model
from learning_coach.schemas import Diagnostic


def completed(args, *, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_codex_cli_plain_invocation_uses_logged_in_cli_and_last_message_file() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text("讲解结果", encoding="utf-8")
        return completed(args)

    model = create_cli_chat_model(
        "codex_cli:gpt-test",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    result = model.invoke([("system", "你是教练"), ("user", "解释状态图")])

    assert result.content == "讲解结果"
    args, kwargs = calls[0]
    assert args[:2] == ["/usr/bin/codex", "exec"]
    assert ["--model", "gpt-test"] == args[args.index("--model") : args.index("--model") + 2]
    assert "--ephemeral" in args
    assert kwargs["input"].startswith("<system>\n你是教练")


def test_codex_cli_structured_output_uses_output_schema() -> None:
    def runner(args, **kwargs):
        schema_path = Path(args[args.index("--output-schema") + 1])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["properties"]["difficulty"]["enum"] == [
            "foundation",
            "application",
            "advanced",
        ]
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "question": "什么是条件边？",
                    "focus": "条件路由",
                    "difficulty": "foundation",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return completed(args)

    model = create_cli_chat_model(
        "codex_cli:gpt-test",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    ).with_structured_output(Diagnostic, method="json_schema")

    result = model.invoke("生成诊断题")

    assert result.focus == "条件路由"


def test_claude_code_structured_output_reads_structured_output_field() -> None:
    def runner(args, **kwargs):
        assert args[:2] == ["/usr/bin/claude", "--safe-mode"]
        assert "--json-schema" in args
        return completed(
            args,
            stdout=json.dumps(
                {
                    "structured_output": {
                        "question": "Reducer 有什么作用？",
                        "focus": "状态合并",
                        "difficulty": "application",
                    }
                },
                ensure_ascii=False,
            ),
        )

    model = create_cli_chat_model(
        "claude_code:sonnet",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    ).with_structured_output(Diagnostic, method="json_schema")

    result = model.invoke("生成诊断题")

    assert result.difficulty == "application"


def test_gemini_cli_prompt_json_retries_once_after_invalid_output() -> None:
    responses = iter(
        [
            {"response": "这不是 JSON"},
            {
                "response": json.dumps(
                    {
                        "question": "何时使用 interrupt？",
                        "focus": "人工输入",
                        "difficulty": "advanced",
                    },
                    ensure_ascii=False,
                )
            },
        ]
    )
    prompts: list[str] = []

    def runner(args, **kwargs):
        prompts.append(args[args.index("--prompt") + 1])
        return completed(args, stdout=json.dumps(next(responses), ensure_ascii=False))

    model = create_cli_chat_model(
        "gemini_cli:gemini-test",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    ).with_structured_output(Diagnostic, method="prompt_json")

    result = model.invoke("生成诊断题")

    assert result.question == "何时使用 interrupt？"
    assert len(prompts) == 2
    assert "上一次输出没有通过" in prompts[1]


def test_codex_cli_materializes_base64_images_for_image_flag() -> None:
    image_bytes = b"test-image-bytes"

    def runner(args, **kwargs):
        image_path = Path(args[args.index("--image") + 1])
        assert image_path.suffix == ".png"
        assert image_path.read_bytes() == image_bytes
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text("看到了图片", encoding="utf-8")
        return completed(args)

    model = create_cli_chat_model(
        "codex_cli:gpt-test",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )
    block = {
        "type": "image",
        "base64": base64.b64encode(image_bytes).decode("ascii"),
        "mime_type": "image/png",
    }

    result = model.invoke(
        [{"role": "user", "content": [{"type": "text", "text": "解释图片"}, block]}]
    )

    assert result.content == "看到了图片"


def test_cli_models_reject_remote_image_urls_instead_of_downloading_them() -> None:
    model = create_cli_chat_model(
        "codex_cli:gpt-test",
        runner=lambda *args, **kwargs: pytest.fail("runner should not be called"),
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    with pytest.raises(RuntimeError, match="CLI 登录模式只支持本地图片"):
        model.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "解释图片"},
                        {"type": "image", "url": "https://example.com/a.png"},
                    ],
                }
            ]
        )


def test_missing_cli_executable_has_actionable_error() -> None:
    model = create_cli_chat_model(
        "gemini_cli:default",
        executable_resolver=lambda name: None,
    )

    with pytest.raises(RuntimeError, match="找不到 gemini CLI"):
        model.invoke("hello")


def test_cli_nonzero_exit_does_not_expose_command_or_credentials() -> None:
    def runner(args, **kwargs):
        return completed(args, returncode=1, stderr="not logged in")

    model = create_cli_chat_model(
        "claude_code:sonnet",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    with pytest.raises(RuntimeError, match="claude CLI 调用失败：not logged in"):
        model.invoke("hello")


def test_cli_timeout_has_actionable_error() -> None:
    def runner(args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=kwargs["timeout"])

    model = create_cli_chat_model(
        "codex_cli:default",
        timeout_seconds=7,
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    with pytest.raises(RuntimeError, match="超过 7 秒"):
        model.invoke("hello")
