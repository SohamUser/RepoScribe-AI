from __future__ import annotations

import shutil
from collections.abc import Callable

from app.ai.service import AIService
from app.ingestion.metadata_extractor import RepositoryMetadataExtractor
from app.ingestion.repository_loader import RepositoryLoader
from app.indexing.service import IncrementalIndexingService

ProgressCallback = Callable[[int, str, str], None]


def process_repository_job(
    repository_url: str,
    branch: str,
    regenerate_doc_types: list[str] | None = None,
    trigger_event: str | None = None,
    trigger_action: str | None = None,
    requested_commit_sha: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    loader = RepositoryLoader()
    extractor = RepositoryMetadataExtractor()
    ai_service = AIService()
    indexing_service = IncrementalIndexingService()
    repository_root = None

    def report(progress: int, stage: str, message: str) -> None:
        if progress_callback is not None:
            progress_callback(progress, stage, message)

    try:
        report(5, "cloning", "Cloning repository")
        repository_root, canonical_url, owner, repository_name = loader.clone_public_repository(
            repository_url=repository_url,
            branch=branch,
        )
        commit_sha = loader.get_head_commit_sha(repository_root)

        report(20, "metadata", "Extracting repository metadata")
        metadata = extractor.extract(
            repository_root=repository_root,
            repository_url=canonical_url,
            owner=owner,
            branch=branch,
        )

        report(35, "diffing", "Detecting changed files from previous index state")
        report(50, "parsing", "Reprocessing only modified repository files")
        incremental = indexing_service.index_repository(
            repository_root=repository_root,
            repository=f"{owner}/{repository_name}",
            branch=branch,
            commit_sha=commit_sha,
        )
        parse_result = incremental["graph"]
        vector_index = incremental["vector_index"]

        report(90, "summarizing", "Generating repository summary")
        summary = ai_service.summarize_repository(repository_name, parse_result)

        regenerated_docs: dict[str, object] = {}
        doc_types = regenerate_doc_types or []
        if doc_types:
            report(95, "documentation", "Regenerating affected documentation")
            for doc_type in doc_types:
                regenerated_docs[doc_type] = ai_service.generate_documentation(
                    repository_name=f"{owner}/{repository_name}",
                    doc_type=doc_type,
                )

        result = {
            "repository_url": canonical_url,
            "branch": branch,
            "commit_sha": commit_sha,
            "requested_commit_sha": requested_commit_sha,
            "previous_commit_sha": incremental["previous_commit_sha"],
            "status": "completed",
            "trigger_event": trigger_event,
            "trigger_action": trigger_action,
            "summary": summary,
            "frameworks": metadata.frameworks,
            "languages": metadata.languages,
            "ast": parse_result,
            "changed_files": incremental["changed_files"],
            "removed_files": incremental["removed_files"],
            "files_reprocessed": incremental["files_reprocessed"],
            "regenerated_docs": regenerated_docs,
            "vector_index": vector_index,
        }
        report(100, "completed", "Repository analysis completed")
        return result
    finally:
        indexing_service.close()
        ai_service.close()
        if repository_root is not None and repository_root.parent.exists():
            shutil.rmtree(repository_root.parent, ignore_errors=True)
