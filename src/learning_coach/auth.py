import shutil
import subprocess
from collections.abc import Callable
from typing import Literal

AuthProvider = Literal["codex", "claude", "gemini"]
AuthAction = Literal["login", "status", "logout"]

_AUTH_COMMANDS: dict[AuthProvider, dict[AuthAction, tuple[str, ...] | None]] = {
    "codex": {
        "login": ("login",),
        "status": ("login", "status"),
        "logout": ("logout",),
    },
    "claude": {
        "login": ("auth", "login"),
        "status": ("auth", "status", "--text"),
        "logout": ("auth", "logout"),
    },
    "gemini": {
        "login": (),
        "status": None,
        "logout": None,
    },
}


def run_auth_action(
    provider: AuthProvider,
    action: AuthAction,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    executable_resolver: Callable[[str], str | None] = shutil.which,
) -> int:
    """Delegate authentication to an official CLI without reading its token files."""

    executable_name = "claude" if provider == "claude" else provider
    executable = executable_resolver(executable_name)
    if executable is None:
        raise RuntimeError(
            f"找不到 {executable_name} CLI。请先安装官方 CLI，再重新执行登录命令。"
        )

    suffix = _AUTH_COMMANDS[provider][action]
    if suffix is None:
        if provider == "gemini" and action == "status":
            raise RuntimeError(
                "Gemini CLI 没有无请求的 status 命令；"
                "请运行登录命令并在官方 /auth 界面查看状态。"
            )
        raise RuntimeError(
            "Gemini CLI 没有独立的 logout 命令；"
            "请启动 gemini，在官方 /auth 界面切换或退出账号。"
        )

    if provider == "gemini":
        print("Gemini CLI 启动后，请在官方界面选择 Sign in with Google；已有会话可直接退出。")

    command = [executable, *suffix]
    result = runner(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"{provider} {action} 未完成，官方 CLI 退出码为 {result.returncode}。"
        )
    return result.returncode
