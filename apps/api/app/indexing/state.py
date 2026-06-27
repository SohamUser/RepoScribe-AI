from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from redis import Redis

from app.core.config import get_settings
from app.ingestion.metadata_extractor import IGNORED_DIRECTORIES, IGNORED_EXTENSIONS


@dataclass(slots=True)
class IncrementalDiff:
    changed_files: list[str]
    removed_files: list[str]
    unchanged_files: list[str]
    current_hashes: dict[str, str]
    previous_commit_sha: str | None


class RepositoryIndexStateStore:
    def __init__(self, redis_client: Redis | None = None) -> None:
        settings = get_settings()
        self.redis = redis_client or Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self.prefix = "repo-index-state"

    def close(self) -> None:
        self.redis.close()

    def load(self, repository: str, branch: str) -> dict[str, Any] | None:
        raw = self.redis.get(self._key(repository, branch))
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def save(self, repository: str, branch: str, state: dict[str, Any]) -> None:
        self.redis.set(self._key(repository, branch), json.dumps(state))

    def diff_repository(
        self,
        *,
        repository_root: Path,
        repository: str,
        branch: str,
    ) -> IncrementalDiff:
        previous = self.load(repository, branch) or {}
        previous_hashes = previous.get("file_hashes", {})
        if not isinstance(previous_hashes, dict):
            previous_hashes = {}

        current_hashes = self._hash_repository_files(repository_root)
        changed_files = [
            path
            for path, digest in current_hashes.items()
            if previous_hashes.get(path) != digest
        ]
        removed_files = [path for path in previous_hashes if path not in current_hashes]
        unchanged_files = [
            path for path, digest in current_hashes.items() if previous_hashes.get(path) == digest
        ]
        previous_commit_sha = previous.get("commit_sha")
        if not isinstance(previous_commit_sha, str):
            previous_commit_sha = None

        return IncrementalDiff(
            changed_files=sorted(changed_files),
            removed_files=sorted(removed_files),
            unchanged_files=sorted(unchanged_files),
            current_hashes=current_hashes,
            previous_commit_sha=previous_commit_sha,
        )

    def _hash_repository_files(self, repository_root: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in sorted(repository_root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(repository_root)
            if any(part in IGNORED_DIRECTORIES for part in relative.parts):
                continue
            if path.suffix.lower() in IGNORED_EXTENSIONS:
                continue
            hashes[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
        return hashes

    def _key(self, repository: str, branch: str) -> str:
        safe_repository = repository.replace("/", ":")
        return f"{self.prefix}:{safe_repository}:{branch}"
