from pathlib import Path
from hashlib import sha256

from app.indexing.state import RepositoryIndexStateStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        return True

    def close(self) -> None:
        return None


def test_state_store_detects_changed_and_removed_files(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    (repository_root / "src").mkdir()
    (repository_root / "src" / "main.py").write_text("print('new')\n", encoding="utf-8")
    keep_contents = "print('same')\n"
    (repository_root / "src" / "keep.py").write_text(keep_contents, encoding="utf-8")

    store = RepositoryIndexStateStore(redis_client=FakeRedis())  # type: ignore[arg-type]
    store.save(
        "acme/repo",
        "main",
        {
            "commit_sha": "abc123",
            "file_hashes": {
                "src/main.py": "old-hash",
                "src/keep.py": sha256(keep_contents.encode("utf-8")).hexdigest(),
                "src/removed.py": "removed-hash",
            },
        },
    )

    diff = store.diff_repository(
        repository_root=repository_root,
        repository="acme/repo",
        branch="main",
    )

    assert diff.previous_commit_sha == "abc123"
    assert "src/main.py" in diff.changed_files
    assert "src/removed.py" in diff.removed_files
    assert "src/keep.py" in diff.unchanged_files
