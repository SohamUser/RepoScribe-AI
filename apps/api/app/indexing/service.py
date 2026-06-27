from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.indexing.state import RepositoryIndexStateStore
from app.parsers.ast_parser import ASTParser
from app.vector.service import VectorService

logger = get_logger(__name__)


class IncrementalIndexingService:
    def __init__(
        self,
        *,
        parser: ASTParser | None = None,
        vector_service: VectorService | None = None,
        state_store: RepositoryIndexStateStore | None = None,
    ) -> None:
        self.parser = parser or ASTParser()
        self.vector_service = vector_service or VectorService()
        self.state_store = state_store or RepositoryIndexStateStore()

    def close(self) -> None:
        self.vector_service.close()
        self.state_store.close()

    def index_repository(
        self,
        *,
        repository_root: Path,
        repository: str,
        branch: str,
        commit_sha: str,
    ) -> dict[str, Any]:
        diff = self.state_store.diff_repository(
            repository_root=repository_root,
            repository=repository,
            branch=branch,
        )
        previous_state = self.state_store.load(repository, branch) or {}
        previous_files = previous_state.get("parsed_files", {})
        if not isinstance(previous_files, dict):
            previous_files = {}

        changed_paths = [repository_root / relative for relative in diff.changed_files]
        changed_parse_result = self.parser.parse_files(repository_root, changed_paths)
        changed_files = self._file_map(changed_parse_result.get("files"))
        merged_files = {
            path: payload
            for path, payload in previous_files.items()
            if path not in diff.changed_files and path not in diff.removed_files
        }
        merged_files.update(changed_files)

        merged_parse_result = self._build_merged_parse_result(
            repository_root=repository_root,
            files_by_path=merged_files,
        )
        changed_chunks = self.vector_service.build_chunks(
            repository_root,
            {"files": list(changed_files.values())},
        )

        vector_index = self.vector_service.index_repository_incremental(
            repository_name=repository,
            chunks=changed_chunks,
            changed_file_paths=diff.changed_files,
            removed_file_paths=diff.removed_files,
        )

        next_state = {
            "repository": repository,
            "branch": branch,
            "commit_sha": commit_sha,
            "file_hashes": diff.current_hashes,
            "parsed_files": merged_files,
            "graph": merged_parse_result,
        }
        self.state_store.save(repository, branch, next_state)

        logger.info(
            "indexing.incremental_completed",
            repository=repository,
            branch=branch,
            commit_sha=commit_sha,
            changed_file_count=len(diff.changed_files),
            removed_file_count=len(diff.removed_files),
        )

        return {
            "repository": repository,
            "branch": branch,
            "commit_sha": commit_sha,
            "previous_commit_sha": diff.previous_commit_sha,
            "changed_files": diff.changed_files,
            "removed_files": diff.removed_files,
            "unchanged_files": diff.unchanged_files,
            "files_reprocessed": len(diff.changed_files),
            "graph": merged_parse_result,
            "vector_index": vector_index,
        }

    def _file_map(self, value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, list):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            if isinstance(path, str) and path:
                result[path] = item
        return result

    def _build_merged_parse_result(
        self,
        *,
        repository_root: Path,
        files_by_path: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        files = [files_by_path[path] for path in sorted(files_by_path)]
        languages = sorted({str(item.get("language")) for item in files if item.get("language")})
        stats = {
            "file_count": len(files),
            "file_count_estimate": len(files),
            "function_count": sum(len(item.get("functions", [])) for item in files),
            "class_count": sum(len(item.get("classes", [])) for item in files),
            "import_count": sum(len(item.get("imports", [])) for item in files),
            "export_count": sum(len(item.get("exports", [])) for item in files),
            "api_count": sum(len(item.get("apis", [])) for item in files),
            "comment_count": sum(len(item.get("comments", [])) for item in files),
        }
        return {
            "repository_path": repository_root.as_posix(),
            "languages": languages,
            "stats": stats,
            "files": files,
        }
