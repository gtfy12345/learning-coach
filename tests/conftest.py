import pytest


@pytest.fixture(autouse=True)
def _hermetic_memory_environment(monkeypatch: pytest.MonkeyPatch):
    """Keep tests independent of a developer's local .env persistence config.

    ``load_dotenv()`` inside the app can import CHECKPOINT_DB_PATH /
    MEMORY_DB_PATH from a local .env into ``os.environ`` mid-suite, which
    would silently wire unrelated tests to shared SQLite files. Tests must
    stay on the in-memory defaults unless a test opts in explicitly.
    """

    for name in ("CHECKPOINT_DB_PATH", "MEMORY_DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    yield
