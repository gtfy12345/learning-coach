import subprocess

import pytest

from learning_coach.auth import run_auth_action


def test_codex_login_delegates_to_official_cli() -> None:
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    assert (
        run_auth_action(
            "codex",
            "login",
            runner=runner,
            executable_resolver=lambda name: f"/usr/bin/{name}",
        )
        == 0
    )
    assert calls == [["/usr/bin/codex", "login"]]


def test_claude_status_uses_machine_safe_status_command() -> None:
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    run_auth_action(
        "claude",
        "status",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    assert calls == [["/usr/bin/claude", "auth", "status", "--text"]]


def test_gemini_login_launches_official_interactive_auth_ui() -> None:
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    run_auth_action(
        "gemini",
        "login",
        runner=runner,
        executable_resolver=lambda name: f"/usr/bin/{name}",
    )

    assert calls == [["/usr/bin/gemini"]]


def test_gemini_status_is_not_faked_with_a_billable_model_call() -> None:
    with pytest.raises(RuntimeError, match="没有无请求的 status 命令"):
        run_auth_action(
            "gemini",
            "status",
            executable_resolver=lambda name: f"/usr/bin/{name}",
        )


def test_auth_action_rejects_missing_cli() -> None:
    with pytest.raises(RuntimeError, match="找不到 codex CLI"):
        run_auth_action("codex", "login", executable_resolver=lambda name: None)
