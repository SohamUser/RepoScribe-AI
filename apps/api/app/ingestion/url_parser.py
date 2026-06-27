import re

from app.core.errors import AppError

GITHUB_REPOSITORY_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def parse_github_repository_url(repository_url: str) -> tuple[str, str, str]:
    normalized_url = repository_url.strip()
    match = GITHUB_REPOSITORY_PATTERN.match(normalized_url)
    if not match:
        raise AppError(
            message="Only public GitHub repository URLs in https://github.com/<owner>/<repo> format are supported.",
            code="invalid_repository_url",
        )

    owner = match.group("owner")
    repository_name = match.group("name")
    canonical_url = f"https://github.com/{owner}/{repository_name}.git"
    return canonical_url, owner, repository_name
