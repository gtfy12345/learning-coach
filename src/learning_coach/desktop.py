"""macOS 桌面应用入口：进程内启动本地服务，并用原生窗口加载页面。

无 GUI 场景（自动化冒烟测试、远程开发机）可用 ``--headless`` 只启动
本地服务。环境引导把 ``.env``、SQLite 持久化与 CLI 模型所需的 PATH
都收敛到独立的数据目录，避免依赖打包后的只读资源位置。
"""

from __future__ import annotations

import argparse
import fcntl
import os
import socket
import sys
import threading
import time
import urllib.request
from collections.abc import Mapping, MutableMapping, Sequence
from pathlib import Path
from typing import Any

APP_DIR_NAME = "LearningCoach"
DATA_HOME_ENV = "LEARNING_COACH_DATA_HOME"
DEFAULT_HOST = "127.0.0.1"
HEALTH_PATH = "/api/health"
DEFAULT_HEALTH_TIMEOUT_SECONDS = 30.0
DEFAULT_WINDOW_TITLE = "Learning Coach"
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0

# Finder 启动的 GUI 进程只继承最小 PATH（/usr/bin:/bin:...），补齐常见
# CLI 安装位置后 codex/claude/gemini CLI 模型才能被 shutil.which 找到。
DEFAULT_EXTRA_PATH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
HOME_EXTRA_PATH_DIRS = (".local/bin", "bin")


def resolve_data_home(
    environ: Mapping[str, str], *, platform: str = sys.platform
) -> Path:
    """桌面模式的数据目录：优先环境变量覆盖，其次按平台默认位置。"""

    override = environ.get(DATA_HOME_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = environ.get("XDG_DATA_HOME", "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def augment_path(
    environ: MutableMapping[str, str],
    *,
    extra_dirs: Sequence[Path] | None = None,
) -> None:
    """把常见可执行目录追加到 PATH 末尾；幂等且不覆盖已有条目。"""

    home = Path.home()
    if extra_dirs is None:
        candidates = [Path(item) for item in DEFAULT_EXTRA_PATH_DIRS]
        candidates += [home / name for name in HOME_EXTRA_PATH_DIRS]
    else:
        candidates = list(extra_dirs)
    entries = [item for item in environ.get("PATH", "").split(os.pathsep) if item]
    missing = [
        str(path)
        for path in candidates
        if path.is_dir() and str(path) not in entries
    ]
    if missing:
        environ["PATH"] = os.pathsep.join(entries + missing)


def bootstrap_environment(environ: MutableMapping[str, str] = os.environ) -> Path:
    """准备桌面运行环境并返回数据目录。

    加载数据目录中的 ``.env``（已导出的环境变量优先），未显式配置持久化
    时默认把检查点与长期记忆落到数据目录的 SQLite 文件，退出应用不丢会话。
    """

    data_home = resolve_data_home(environ)
    data_home.mkdir(parents=True, exist_ok=True)
    env_path = data_home / ".env"
    if env_path.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    environ.setdefault("CHECKPOINT_DB_PATH", str(data_home / "checkpoints.db"))
    environ.setdefault("MEMORY_DB_PATH", str(data_home / "memory.db"))
    augment_path(environ)
    return data_home


class SingleInstanceLock:
    """基于 flock 的单实例锁：进程退出或崩溃时由系统自动释放。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        if sys.platform == "win32":
            return True
        fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def pick_free_port(host: str = DEFAULT_HOST) -> int:
    """让系统分配一个当前空闲的回环端口。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def start_local_server(
    app: Any, *, host: str, port: int
) -> tuple[Any, threading.Thread]:
    """在后台线程运行 uvicorn，返回 (server, thread) 供优雅停机。"""

    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run, name="learning-coach-desktop-server", daemon=True
    )
    thread.start()
    return server, thread


def wait_for_health(
    host: str,
    port: int,
    *,
    timeout: float = DEFAULT_HEALTH_TIMEOUT_SECONDS,
    poll_seconds: float = 0.1,
    url_path: str = HEALTH_PATH,
) -> bool:
    """轮询健康检查直到就绪或超时。"""

    url = f"http://{host}:{port}{url_path}"
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if response.status == 200:
                    return True
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)


def build_application(env_file: Path) -> Any:
    """构造桌面版 FastAPI 应用：注入数据目录中的 .env 作为持久化目标。"""

    from learning_coach.web import LearningSessionService, create_app

    return create_app(service=LearningSessionService(env_file=env_file))


def run_gui(url: str, *, title: str = DEFAULT_WINDOW_TITLE) -> None:
    """打开原生窗口（WKWebView）；懒加载以便无头环境导入本模块。"""

    import webview

    webview.create_window(title, url, width=1280, height=860, min_size=(1000, 680))
    webview.start()


def _show_message_window(title: str, message: str) -> None:
    import webview

    webview.create_window(title, html=message, width=440, height=180)
    webview.start()


def _parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m learning_coach desktop",
        description="启动 Learning Coach 桌面窗口：本地服务 + 原生窗口。",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="只启动本地服务不打开窗口，用于冒烟测试",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="固定服务端口；默认自动选择空闲端口",
    )
    parser.add_argument(
        "--data-home",
        metavar="PATH",
        help="覆盖数据目录；默认 ~/Library/Application Support/LearningCoach",
    )
    return parser.parse_args(argv)


def run_desktop(argv: Sequence[str] | None = None) -> int:
    """桌面入口主流程；返回进程退出码。"""

    args = _parse_arguments(list(sys.argv[1:] if argv is None else argv))
    if args.data_home is not None and not args.data_home.strip():
        raise SystemExit("--data-home 不能为空。")
    if args.data_home:
        os.environ[DATA_HOME_ENV] = args.data_home.strip()

    data_home = bootstrap_environment()
    lock = SingleInstanceLock(data_home / "app.lock")
    if not lock.acquire():
        if args.headless:
            print("Learning Coach 已在运行，本次启动退出。", file=sys.stderr)
        else:
            _show_message_window(
                DEFAULT_WINDOW_TITLE,
                "<p style='font-family:-apple-system;font-size:14px;"
                "padding:8px'>Learning Coach 已在运行。</p>",
            )
        return 1

    port = args.port if args.port else pick_free_port()
    application = build_application(data_home / ".env")
    server, server_thread = start_local_server(application, host=DEFAULT_HOST, port=port)
    url = f"http://{DEFAULT_HOST}:{port}/"
    if not wait_for_health(DEFAULT_HOST, port):
        print(f"本地服务未能在限时内就绪：{url}", file=sys.stderr)
        server.should_exit = True
        server_thread.join(timeout=DEFAULT_SHUTDOWN_TIMEOUT_SECONDS)
        lock.release()
        return 1

    try:
        if args.headless:
            print(f"Learning Coach 本地服务已启动：{url}（Ctrl+C 退出）")
            while server_thread.is_alive():
                server_thread.join(0.5)
        else:
            run_gui(url)
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        server_thread.join(timeout=DEFAULT_SHUTDOWN_TIMEOUT_SECONDS)
        lock.release()
    return 0
