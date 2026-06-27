import asyncio
import shutil
from pathlib import Path

from app.ingestion.metadata_extractor import RepositoryMetadataExtractor
from app.ingestion.repository_loader import RepositoryLoader
from app.schemas.repository import RepositoryMetadataResponse

class IngestionService:
    def __init__(self) -> None:
        self.loader = RepositoryLoader()
        self.extractor = RepositoryMetadataExtractor()

    async def ingest_repository(self, repository_url: str, branch: str) -> RepositoryMetadataResponse:
        return await asyncio.to_thread(self._ingest_repository_sync, repository_url, branch)

    def _ingest_repository_sync(self, repository_url: str, branch: str) -> RepositoryMetadataResponse:
        repository_root: Path | None = None
        workspace_root: Path | None = None

        try:
            repository_root, canonical_url, owner, _ = self.loader.clone_public_repository(repository_url, branch)
            workspace_root = repository_root.parent
            return self.extractor.extract(
                repository_root=repository_root,
                repository_url=canonical_url,
                owner=owner,
                branch=branch,
            )
        finally:
            if workspace_root and workspace_root.exists():
                shutil.rmtree(workspace_root, ignore_errors=True)
