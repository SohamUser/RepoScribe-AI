import tempfile
from pathlib import Path

from git import GitCommandError, Repo

from app.core.errors import AppError
from app.core.logging import get_logger
from app.ingestion.url_parser import parse_github_repository_url

logger = get_logger(__name__)


class RepositoryLoader:
    def clone_public_repository(self, repository_url: str, branch: str) -> tuple[Path, str, str, str]:
        canonical_url, owner, repository_name = parse_github_repository_url(repository_url)
        workspace = Path(tempfile.mkdtemp(prefix="repo-ingestion-"))
        target_directory = workspace / repository_name

        try:
            Repo.clone_from(
                canonical_url,
                target_directory,
                branch=branch,
                depth=1,
                single_branch=True,
            )
        except GitCommandError as exc:
            logger.warning("repository.clone_failed", repository_url=repository_url, error=str(exc))
            raise AppError(
                message="Failed to clone the repository. Confirm the URL, branch, and that the repository is public.",
                code="repository_clone_failed",
            ) from exc

        return target_directory, canonical_url, owner, repository_name

    def get_head_commit_sha(self, repository_root: Path) -> str:
        repo = Repo(repository_root)
        return repo.head.commit.hexsha
