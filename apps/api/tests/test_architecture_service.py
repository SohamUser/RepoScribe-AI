from pathlib import Path

from app.architecture.service import ArchitectureVisualizationService


def test_architecture_service_detects_microservices_and_generates_mermaid(tmp_path: Path) -> None:
    repository_root = tmp_path / "sample-repo"
    repository_root.mkdir()

    api_service = repository_root / "api"
    api_service.mkdir()
    (api_service / "pyproject.toml").write_text("[project]\nname='api'\n", encoding="utf-8")

    worker_service = repository_root / "worker"
    worker_service.mkdir()
    (worker_service / "requirements.txt").write_text("fastapi\nredis\n", encoding="utf-8")

    parsed_repository = {
        "files": [
            {
                "path": "api/main.py",
                "language": "Python",
                "dependencies": ["fastapi", "app.services.user_service"],
                "apis": [{"name": "list_users", "method": "GET", "route": "/users"}],
            },
            {
                "path": "worker/jobs.py",
                "language": "Python",
                "dependencies": ["redis", "api.main"],
                "apis": [],
            },
        ]
    }
    metadata = {
        "repository_url": "https://github.com/acme/sample-repo.git",
        "repository_name": "sample-repo",
        "owner": "acme",
        "branch": "main",
    }

    result = ArchitectureVisualizationService()._build_response(
        repository_root=repository_root,
        metadata=metadata,
        parsed_repository=parsed_repository,
    )

    assert result.architecture_type == "microservices"
    assert result.detected_services == ["api", "worker"]
    assert "```mermaid" in result.dependency_graph_markdown
    assert 'GET /users' in result.api_flow_diagram_markdown
    assert "Architecture: microservices" in result.service_diagram_markdown


def test_architecture_service_falls_back_to_monolith(tmp_path: Path) -> None:
    repository_root = tmp_path / "mono-repo"
    repository_root.mkdir()
    src = repository_root / "src"
    src.mkdir()
    (src / "package.json").write_text('{"name":"mono"}', encoding="utf-8")

    parsed_repository = {
        "files": [
            {
                "path": "src/index.ts",
                "language": "TypeScript",
                "dependencies": ["express", "./routes"],
                "apis": [{"name": "health", "method": "GET", "route": "/health"}],
            }
        ]
    }
    metadata = {
        "repository_url": "https://github.com/acme/mono-repo.git",
        "repository_name": "mono-repo",
        "owner": "acme",
        "branch": "main",
    }

    result = ArchitectureVisualizationService()._build_response(
        repository_root=repository_root,
        metadata=metadata,
        parsed_repository=parsed_repository,
    )

    assert result.architecture_type == "monolith"
    assert result.detected_services == ["src"]
    assert "src/index.ts" in result.dependency_graph_markdown
    assert "/health" in result.api_flow_diagram_markdown
