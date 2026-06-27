from pathlib import Path

from app.ingestion.metadata_extractor import RepositoryMetadataExtractor
from app.ingestion.url_parser import parse_github_repository_url


def test_parse_github_repository_url_accepts_public_https_url() -> None:
    canonical_url, owner, repository_name = parse_github_repository_url(
        "https://github.com/openai/openai-python"
    )
    assert canonical_url == "https://github.com/openai/openai-python.git"
    assert owner == "openai"
    assert repository_name == "openai-python"


def test_metadata_extractor_ignores_build_artifacts(tmp_path: Path) -> None:
    repository_root = tmp_path / "sample-repo"
    repository_root.mkdir()
    (repository_root / "package.json").write_text(
        '{"dependencies":{"next":"15.0.0","react":"19.0.0"}}',
        encoding="utf-8",
    )
    (repository_root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'", encoding="utf-8")
    (repository_root / "src").mkdir()
    (repository_root / "src" / "main.ts").write_text("export const ok = true;", encoding="utf-8")
    (repository_root / "node_modules").mkdir()
    (repository_root / "node_modules" / "ignored.js").write_text("ignored", encoding="utf-8")
    (repository_root / "dist").mkdir()
    (repository_root / "dist" / "bundle.js").write_text("ignored", encoding="utf-8")

    metadata = RepositoryMetadataExtractor().extract(
        repository_root=repository_root,
        repository_url="https://github.com/acme/sample-repo.git",
        owner="acme",
        branch="main",
    )

    assert metadata.repository_name == "sample-repo"
    assert "TypeScript" in metadata.languages
    assert "pnpm" in metadata.package_managers
    assert "Next.js" in metadata.frameworks
    assert "React" in metadata.frameworks
    assert all("node_modules/" not in node.path for node in metadata.file_tree)
    assert all("dist/" not in node.path for node in metadata.file_tree)
