import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from learning_coach import cli, desktop


def test_resolve_data_home_honors_override(tmp_path: Path) -> None:
    environ = {desktop.DATA_HOME_ENV: str(tmp_path)}
    assert desktop.resolve_data_home(environ) == tmp_path


def test_resolve_data_home_darwin_default(monkeypatch) -> None:
    monkeypatch.delenv(desktop.DATA_HOME_ENV, raising=False)
    home = desktop.resolve_data_home({}, platform="darwin")
    assert home == Path.home() / "Library" / "Application Support" / desktop.APP_DIR_NAME


def test_resolve_data_home_non_darwin_uses_xdg() -> None:
    assert desktop.resolve_data_home(
        {"XDG_DATA_HOME": "/tmp/xdg"}, platform="linux"
    ) == Path("/tmp/xdg") / desktop.APP_DIR_NAME
    assert desktop.resolve_data_home({}, platform="linux") == (
        Path.home() / ".local" / "share" / desktop.APP_DIR_NAME
    )


def test_bootstrap_environment_loads_env_and_defaults_db_paths(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / ".env").write_text(
        "CHAT_MODEL_ID=openai:gpt-5-mini\n", encoding="utf-8"
    )
    monkeypatch.setenv(desktop.DATA_HOME_ENV, str(tmp_path))
    monkeypatch.delenv("CHAT_MODEL_ID", raising=False)
    monkeypatch.delenv("CHECKPOINT_DB_PATH", raising=False)
    monkeypatch.delenv("MEMORY_DB_PATH", raising=False)

    returned = desktop.bootstrap_environment()

    assert returned == tmp_path
    assert os.environ["CHECKPOINT_DB_PATH"] == str(tmp_path / "checkpoints.db")
    assert os.environ["MEMORY_DB_PATH"] == str(tmp_path / "memory.db")
    assert os.environ["CHAT_MODEL_ID"] == "openai:gpt-5-mini"


def test_bootstrap_environment_respects_explicit_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(desktop.DATA_HOME_ENV, str(tmp_path))
    monkeypatch.setenv("CHECKPOINT_DB_PATH", "memory")
    custom_store = tmp_path / "custom-memory.db"
    monkeypatch.setenv("MEMORY_DB_PATH", str(custom_store))

    desktop.bootstrap_environment()

    assert os.environ["CHECKPOINT_DB_PATH"] == "memory"
    assert os.environ["MEMORY_DB_PATH"] == str(custom_store)


def test_augment_path_appends_only_missing_directories(tmp_path: Path) -> None:
    extra = tmp_path / "bin"
    extra.mkdir()
    environ = {"PATH": "/usr/bin:/bin"}

    desktop.augment_path(environ, extra_dirs=[extra])
    assert environ["PATH"] == f"/usr/bin:/bin{os.pathsep}{extra}"

    desktop.augment_path(environ, extra_dirs=[extra])
    assert environ["PATH"].count(str(extra)) == 1


def test_augment_path_ignores_missing_directories(tmp_path: Path) -> None:
    environ = {"PATH": "/usr/bin"}
    desktop.augment_path(environ, extra_dirs=[tmp_path / "nope"])
    assert environ["PATH"] == "/usr/bin"


def test_single_instance_lock_blocks_second_acquire(tmp_path: Path) -> None:
    lock_path = tmp_path / "app.lock"

    first = desktop.SingleInstanceLock(lock_path)
    assert first.acquire()
    second = desktop.SingleInstanceLock(lock_path)
    assert not second.acquire()

    first.release()
    third = desktop.SingleInstanceLock(lock_path)
    assert third.acquire()
    third.release()


def test_pick_free_port_returns_bindable_port() -> None:
    port = desktop.pick_free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == desktop.HEALTH_PATH:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


def test_wait_for_health_returns_true_when_serving() -> None:
    server = HTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert desktop.wait_for_health("127.0.0.1", server.server_port, timeout=5.0)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_wait_for_health_times_out_when_nothing_listens() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = int(sock.getsockname()[1])
    assert not desktop.wait_for_health(
        "127.0.0.1", closed_port, timeout=0.3, poll_seconds=0.05
    )


def test_start_local_server_serves_real_health_endpoint(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(desktop.DATA_HOME_ENV, str(tmp_path))
    desktop.bootstrap_environment()
    application = desktop.build_application(tmp_path / ".env")
    port = desktop.pick_free_port()

    server, server_thread = desktop.start_local_server(
        application, host=desktop.DEFAULT_HOST, port=port
    )
    try:
        assert desktop.wait_for_health(desktop.DEFAULT_HOST, port, timeout=20.0)
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
    assert not server_thread.is_alive()


def test_run_desktop_rejects_blank_data_home() -> None:
    try:
        desktop.run_desktop(["--data-home", "   "])
    except SystemExit as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("空 --data-home 应当直接退出")


def test_cli_dispatches_desktop_subcommand(monkeypatch) -> None:
    recorded: dict[str, list[str]] = {}

    def fake_run_desktop(argv: list[str]) -> int:
        recorded["argv"] = argv
        return 0

    monkeypatch.setattr("learning_coach.desktop.run_desktop", fake_run_desktop)
    cli.main(["desktop", "--headless"])
    assert recorded["argv"] == ["--headless"]
