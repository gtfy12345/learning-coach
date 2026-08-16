import base64
import binascii
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ValidationError

CliStructuredMethod = Literal["json_schema", "function_calling", "prompt_json"]

_IMAGE_SUFFIXES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class CliProviderSpec:
    prefix: str
    executable: str
    display_name: str
    native_structured_output: bool
    prompt_structured_output: bool
    image_inputs: bool
    secret_environment: tuple[str, ...]


_CLI_PROVIDERS = {
    "codex_cli": CliProviderSpec(
        prefix="codex_cli",
        executable="codex",
        display_name="codex",
        native_structured_output=True,
        prompt_structured_output=False,
        image_inputs=True,
        secret_environment=("OPENAI_API_KEY", "CODEX_API_KEY"),
    ),
    "claude_code": CliProviderSpec(
        prefix="claude_code",
        executable="claude",
        display_name="claude",
        native_structured_output=True,
        prompt_structured_output=False,
        image_inputs=True,
        secret_environment=("ANTHROPIC_API_KEY",),
    ),
    "gemini_cli": CliProviderSpec(
        prefix="gemini_cli",
        executable="gemini",
        display_name="gemini",
        native_structured_output=False,
        prompt_structured_output=True,
        image_inputs=True,
        secret_environment=(
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ),
    ),
}


def is_cli_model_id(model_id: str) -> bool:
    prefix, separator, _ = model_id.partition(":")
    return bool(separator and prefix in _CLI_PROVIDERS)


def _parse_model_id(model_id: str) -> tuple[CliProviderSpec, str | None]:
    prefix, separator, model_name = model_id.partition(":")
    if not separator or prefix not in _CLI_PROVIDERS:
        choices = ", ".join(f"{name}:MODEL" for name in _CLI_PROVIDERS)
        raise ValueError(f"CLI 模型 ID 必须使用以下前缀之一：{choices}。")
    normalized_model = model_name.strip()
    if not normalized_model:
        raise ValueError("CLI 模型 ID 的模型名称不能为空。")
    return _CLI_PROVIDERS[prefix], (
        None if normalized_model == "default" else normalized_model
    )


def _role_and_content(message: Any) -> tuple[str, Any]:
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0]), message[1]
    if isinstance(message, Mapping):
        return str(message.get("role", "user")), message.get("content", "")

    role = getattr(message, "type", "user")
    role = {"human": "user", "ai": "assistant"}.get(role, role)
    return str(role), getattr(message, "content", message)


def _message_payload(value: Any) -> tuple[str, list[dict[str, Any]]]:
    messages: Sequence[Any] = [value] if isinstance(value, str) else value
    prompt_parts: list[str] = []
    images: list[dict[str, Any]] = []

    for message in messages:
        role, content = _role_and_content(message)
        text_parts: list[str] = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, Sequence):
            for block in content:
                if not isinstance(block, Mapping):
                    text_parts.append(str(block))
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    text_parts.append(str(block.get("text", "")))
                elif block_type == "image":
                    images.append(dict(block))
                else:
                    text_parts.append(str(dict(block)))
        else:
            text_parts.append(str(content))

        message_text = "\n".join(text_parts)
        prompt_parts.append(f"<{role}>\n{message_text}\n</{role}>")

    return "\n\n".join(prompt_parts), images


def _materialize_images(images: Sequence[dict[str, Any]], directory: Path) -> list[Path]:
    paths: list[Path] = []
    for index, block in enumerate(images, start=1):
        if block.get("url"):
            raise RuntimeError(
                "CLI 登录模式只支持本地图片；图片 URL 不会由 Learning Coach 下载。"
            )
        encoded = block.get("base64")
        mime_type = block.get("mime_type")
        if not isinstance(encoded, str) or mime_type not in _IMAGE_SUFFIXES:
            raise RuntimeError("CLI 登录模式收到无法识别的图片 content block。")
        try:
            image_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("图片 base64 内容无效。") from exc
        path = directory / f"input-{index}{_IMAGE_SUFFIXES[mime_type]}"
        path.write_bytes(image_bytes)
        paths.append(path)
    return paths


def _safe_environment(spec: CliProviderSpec) -> dict[str, str]:
    environment = os.environ.copy()
    for name in spec.secret_environment:
        environment.pop(name, None)
    return environment


def _codex_output_schema(schema: type[BaseModel]) -> dict[str, Any]:
    document = schema.model_json_schema()
    pending: list[Any] = [document]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["additionalProperties"] = False
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return document


def _safe_error(stderr: str, stdout: str) -> str:
    message = (stderr or stdout or "未知错误").strip().replace("\x00", "")
    return message[:500]


def _json_from_text(text: str) -> Any:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        if start < 0:
            raise
        result, _ = json.JSONDecoder().raw_decode(value[start:])
        return result


class CliChatModel:
    """Small LangChain-compatible adapter around an authenticated official CLI."""

    def __init__(
        self,
        model_id: str,
        *,
        timeout_seconds: int = 300,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        executable_resolver: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.model_id = model_id
        self.spec, self.model_name = _parse_model_id(model_id)
        self.timeout_seconds = timeout_seconds
        self.runner = runner
        self.executable_resolver = executable_resolver
        self.profile = {
            "structured_output": self.spec.native_structured_output,
            "tool_calling": False,
            "image_inputs": self.spec.image_inputs,
            "learning_coach_prompt_structured_output": (
                self.spec.prompt_structured_output
            ),
        }

    def with_structured_output(
        self,
        schema: type[BaseModel],
        *,
        method: CliStructuredMethod,
    ) -> "StructuredCliChatModel":
        return StructuredCliChatModel(self, schema, method)

    def invoke(self, value: Any, config: Any | None = None, **kwargs: Any) -> AIMessage:
        prompt, images = _message_payload(value)
        response = self._invoke(prompt, images, schema=None)
        if not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        return AIMessage(content=response)

    def _executable(self) -> str:
        executable = self.executable_resolver(self.spec.executable)
        if executable is None:
            raise RuntimeError(
                f"找不到 {self.spec.display_name} CLI。请先安装官方 CLI，"
                f"再运行 `python -m learning_coach auth login {self.spec.display_name}`。"
            )
        return executable

    def _run(self, args: list[str], *, prompt: str, cwd: Path) -> subprocess.CompletedProcess:
        try:
            result = self.runner(
                args,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                cwd=str(cwd),
                env=_safe_environment(self.spec),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{self.spec.display_name} CLI 调用超过 "
                f"{self.timeout_seconds} 秒，已停止等待。"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"{self.spec.display_name} CLI 调用失败："
                f"{_safe_error(result.stderr, result.stdout)}"
            )
        return result

    def _invoke(
        self,
        prompt: str,
        images: Sequence[dict[str, Any]],
        *,
        schema: type[BaseModel] | None,
    ) -> str | dict[str, Any]:
        executable = self._executable()
        with tempfile.TemporaryDirectory(prefix="learning-coach-cli-") as temp_name:
            temp_dir = Path(temp_name)
            image_paths = _materialize_images(images, temp_dir)
            if self.spec.prefix == "codex_cli":
                return self._invoke_codex(
                    executable, prompt, image_paths, schema, temp_dir
                )
            if self.spec.prefix == "claude_code":
                return self._invoke_claude(
                    executable, prompt, image_paths, schema, temp_dir
                )
            return self._invoke_gemini(
                executable, prompt, image_paths, temp_dir
            )

    def _invoke_codex(
        self,
        executable: str,
        prompt: str,
        image_paths: Sequence[Path],
        schema: type[BaseModel] | None,
        temp_dir: Path,
    ) -> str:
        output_path = temp_dir / "last-message.txt"
        args = [
            executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "--color",
            "never",
            "--output-last-message",
            str(output_path),
        ]
        if self.model_name is not None:
            args.extend(["--model", self.model_name])
        if schema is not None:
            schema_path = temp_dir / "schema.json"
            schema_path.write_text(
                json.dumps(_codex_output_schema(schema), ensure_ascii=False),
                encoding="utf-8",
            )
            args.extend(["--output-schema", str(schema_path)])
        for image_path in image_paths:
            args.extend(["--image", str(image_path)])
        args.append("-")
        self._run(args, prompt=prompt, cwd=temp_dir)
        if not output_path.is_file():
            raise RuntimeError("codex CLI 没有生成最终消息文件。")
        return output_path.read_text(encoding="utf-8").strip()

    def _invoke_claude(
        self,
        executable: str,
        prompt: str,
        image_paths: Sequence[Path],
        schema: type[BaseModel] | None,
        temp_dir: Path,
    ) -> str | dict[str, Any]:
        if image_paths:
            prompt += "\n\n请使用 Read 工具读取以下图片后回答：\n" + "\n".join(
                str(path) for path in image_paths
            )
        args = [
            executable,
            "--safe-mode",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "Read" if image_paths else "",
            "--output-format",
            "json",
        ]
        if self.model_name is not None:
            args.extend(["--model", self.model_name])
        if schema is not None:
            args.extend(
                [
                    "--json-schema",
                    json.dumps(schema.model_json_schema(), ensure_ascii=False),
                ]
            )
        args.append("--print")
        result = self._run(args, prompt=prompt, cwd=temp_dir)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("claude CLI 返回了无法解析的 JSON。") from exc
        if schema is not None:
            structured = payload.get("structured_output")
            if structured is None:
                raise RuntimeError("claude CLI 没有返回 structured_output。")
            return (
                _json_from_text(structured)
                if isinstance(structured, str)
                else structured
            )
        response = payload.get("result", payload.get("response"))
        if not isinstance(response, str):
            raise RuntimeError("claude CLI 没有返回文本结果。")
        return response

    def _invoke_gemini(
        self,
        executable: str,
        prompt: str,
        image_paths: Sequence[Path],
        temp_dir: Path,
    ) -> str:
        if image_paths:
            prompt += "\n\n请读取并分析这些图片：\n" + "\n".join(
                f"@{path}" for path in image_paths
            )
        args = [executable, "--output-format", "json"]
        if self.model_name is not None:
            args.extend(["--model", self.model_name])
        args.extend(["--prompt", prompt])
        result = self._run(args, prompt="", cwd=temp_dir)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("gemini CLI 返回了无法解析的 JSON。") from exc
        response = payload.get("response")
        if not isinstance(response, str):
            error = payload.get("error")
            raise RuntimeError(f"gemini CLI 没有返回文本结果：{error or '未知错误'}")
        return response


class StructuredCliChatModel:
    def __init__(
        self,
        model: CliChatModel,
        schema: type[BaseModel],
        method: CliStructuredMethod,
    ) -> None:
        self.model = model
        self.schema = schema
        self.method = method

    def invoke(self, value: Any, config: Any | None = None, **kwargs: Any) -> BaseModel:
        prompt, images = _message_payload(value)
        if self.method == "prompt_json":
            schema_json = json.dumps(
                self.schema.model_json_schema(), ensure_ascii=False
            )
            prompt += (
                "\n\n只返回一个符合下面 JSON Schema 的 JSON 对象。"
                "不要使用 Markdown 代码围栏，不要补充解释。\n"
                f"JSON Schema：{schema_json}"
            )
            last_error: Exception | None = None
            for attempt in range(2):
                attempt_prompt = prompt
                if attempt and last_error is not None:
                    attempt_prompt += (
                        "\n\n上一次输出没有通过结构验证。"
                        f"请修正后只返回 JSON。错误：{last_error}"
                    )
                raw = self.model._invoke(attempt_prompt, images, schema=None)
                try:
                    data = _json_from_text(str(raw))
                    return self.schema.model_validate(data)
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    last_error = exc
            raise RuntimeError(
                f"{self.model.spec.display_name} CLI 两次输出都没有通过结构验证。"
            ) from last_error

        raw = self.model._invoke(prompt, images, schema=self.schema)
        try:
            data = _json_from_text(raw) if isinstance(raw, str) else raw
            return self.schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise RuntimeError(
                f"{self.model.spec.display_name} CLI 的结构化结果没有通过验证。"
            ) from exc


def create_cli_chat_model(
    model_id: str,
    *,
    timeout_seconds: int = 300,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    executable_resolver: Callable[[str], str | None] = shutil.which,
) -> CliChatModel:
    return CliChatModel(
        model_id,
        timeout_seconds=timeout_seconds,
        runner=runner,
        executable_resolver=executable_resolver,
    )
