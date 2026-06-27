from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.ingestion.metadata_extractor import RepositoryMetadataExtractor
from app.ingestion.repository_loader import RepositoryLoader
from app.parsers.ast_parser import ASTParser
from app.schemas.repository import RepositoryArchitectureResponse

SERVICE_MARKER_FILES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "Cargo.toml",
    "Dockerfile",
    "docker-compose.yml",
}

API_KEYWORDS = ("api", "service", "worker", "server", "backend")


class ArchitectureVisualizationService:
    def __init__(self) -> None:
        self.loader = RepositoryLoader()
        self.extractor = RepositoryMetadataExtractor()
        self.parser = ASTParser()

    async def generate_repository_architecture(
        self,
        *,
        repository_url: str,
        branch: str,
    ) -> RepositoryArchitectureResponse:
        repository_root: Path | None = None
        workspace_root: Path | None = None

        try:
            repository_root, canonical_url, owner, _ = self.loader.clone_public_repository(
                repository_url=repository_url,
                branch=branch,
            )
            workspace_root = repository_root.parent
            metadata = self.extractor.extract(
                repository_root=repository_root,
                repository_url=canonical_url,
                owner=owner,
                branch=branch,
            )
            parsed_repository = self.parser.parse_repository(repository_root)
            return self._build_response(
                repository_root=repository_root,
                metadata=metadata.model_dump(),
                parsed_repository=parsed_repository,
            )
        finally:
            if workspace_root and workspace_root.exists():
                shutil.rmtree(workspace_root, ignore_errors=True)

    def _build_response(
        self,
        *,
        repository_root: Path,
        metadata: dict[str, Any],
        parsed_repository: dict[str, Any],
    ) -> RepositoryArchitectureResponse:
        files = self._normalize_files(parsed_repository.get("files"))
        service_groups = self._detect_service_groups(repository_root, files)
        architecture_type = self._detect_architecture_type(service_groups, files)

        dependency_diagram = self._build_dependency_graph(files)
        service_diagram = self._build_service_diagram(service_groups, architecture_type)
        api_flow_diagram = self._build_api_flow_diagram(files)

        return RepositoryArchitectureResponse(
            repository_url=str(metadata.get("repository_url", "")),
            repository_name=str(metadata.get("repository_name", repository_root.name)),
            owner=str(metadata.get("owner", "")),
            branch=str(metadata.get("branch", "")),
            architecture_type=architecture_type,
            detected_services=[group["name"] for group in service_groups],
            dependency_graph_markdown=dependency_diagram,
            service_diagram_markdown=service_diagram,
            api_flow_diagram_markdown=api_flow_diagram,
        )

    def _normalize_files(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _detect_service_groups(
        self,
        repository_root: Path,
        files: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        top_level_dirs = self._top_level_directories(repository_root)
        results: list[dict[str, Any]] = []

        for directory in top_level_dirs:
            directory_name = directory.name
            directory_files = [
                item for item in files if str(item.get("path", "")).startswith(f"{directory_name}/")
            ]
            if not directory_files:
                continue

            marker_score = self._service_marker_score(directory, directory_files)
            api_count = sum(len(self._normalize_items(item.get("apis"))) for item in directory_files)
            dependency_count = sum(len(self._normalize_strings(item.get("dependencies"))) for item in directory_files)
            if marker_score == 0 and api_count == 0 and dependency_count < 2:
                continue

            results.append(
                {
                    "name": directory_name,
                    "apis": api_count,
                    "dependencies": dependency_count,
                    "files": directory_files,
                }
            )

        if not results:
            results.append(
                {
                    "name": repository_root.name,
                    "apis": sum(len(self._normalize_items(item.get("apis"))) for item in files),
                    "dependencies": sum(len(self._normalize_strings(item.get("dependencies"))) for item in files),
                    "files": files,
                }
            )
        return results

    def _detect_architecture_type(
        self,
        service_groups: list[dict[str, Any]],
        files: list[dict[str, Any]],
    ) -> str:
        service_like_groups = [
            group
            for group in service_groups
            if group["name"] != "packages" and (group["apis"] > 0 or group["dependencies"] > 2)
        ]
        root_languages = {str(item.get("language", "")) for item in files if item.get("path")}
        if len(service_like_groups) >= 2:
            return "microservices"
        if len(root_languages) > 1 and service_like_groups:
            return "modular_monolith"
        return "monolith"

    def _build_dependency_graph(self, files: list[dict[str, Any]]) -> str:
        lines = ["```mermaid", "graph TD"]
        added_nodes: set[str] = set()
        added_edges: set[tuple[str, str]] = set()

        for item in files[:80]:
            file_path = str(item.get("path", ""))
            dependencies = self._normalize_strings(item.get("dependencies"))
            if not file_path or not dependencies:
                continue
            source = self._node_id(file_path)
            if source not in added_nodes:
                lines.append(f'    {source}["{self._label(file_path)}"]')
                added_nodes.add(source)
            for dependency in dependencies[:8]:
                target = self._node_id(dependency)
                if target not in added_nodes:
                    lines.append(f'    {target}["{self._label(dependency)}"]')
                    added_nodes.add(target)
                edge = (source, target)
                if edge in added_edges:
                    continue
                lines.append(f"    {source} --> {target}")
                added_edges.add(edge)

        if len(lines) == 2:
            lines.append('    repo["No dependency relationships detected"]')
        lines.append("```")
        return "\n".join(lines)

    def _build_service_diagram(self, service_groups: list[dict[str, Any]], architecture_type: str) -> str:
        lines = ["```mermaid", "graph LR"]
        root_id = "repo"
        lines.append(f'    {root_id}["Architecture: {architecture_type}"]')

        for group in service_groups:
            group_id = self._node_id(group["name"])
            lines.append(f'    {group_id}["{group["name"]}\\nAPIs: {group["apis"]}"]')
            lines.append(f"    {root_id} --> {group_id}")

            frameworks = self._frameworks_for_group(group["files"])
            if frameworks:
                framework_id = f"{group_id}_framework"
                framework_label = ", ".join(frameworks[:3])
                lines.append(f'    {framework_id}["{framework_label}"]')
                lines.append(f"    {group_id} --> {framework_id}")

        lines.append("```")
        return "\n".join(lines)

    def _build_api_flow_diagram(self, files: list[dict[str, Any]]) -> str:
        lines = ["```mermaid", "flowchart TD", '    client["Client"]']
        api_edges = 0

        for item in files[:80]:
            file_path = str(item.get("path", ""))
            apis = self._normalize_items(item.get("apis"))
            if not file_path or not apis:
                continue
            file_id = self._node_id(file_path)
            lines.append(f'    {file_id}["{self._label(file_path)}"]')
            for api in apis[:8]:
                route = str(api.get("route", "")).strip()
                method = str(api.get("method", "")).strip().upper()
                name = str(api.get("name", "")).strip() or "handler"
                handler_id = self._node_id(f"{file_path}:{name}")
                route_label = f"{method} {route}".strip()
                lines.append(f'    {handler_id}["{route_label}\\n{name}"]')
                lines.append(f"    client --> {handler_id}")
                lines.append(f"    {handler_id} --> {file_id}")
                api_edges += 1

        if api_edges == 0:
            lines.append('    client --> note["No API flows detected"]')
        lines.append("```")
        return "\n".join(lines)

    def _frameworks_for_group(self, files: list[dict[str, Any]]) -> list[str]:
        frameworks: set[str] = set()
        for item in files:
            path = str(item.get("path", "")).lower()
            dependencies = {dependency.lower() for dependency in self._normalize_strings(item.get("dependencies"))}
            if "fastapi" in dependencies:
                frameworks.add("FastAPI")
            if "express" in dependencies:
                frameworks.add("Express")
            if "next" in dependencies or path.endswith("next.config.ts") or path.endswith("next.config.js"):
                frameworks.add("Next.js")
        return sorted(frameworks)

    def _service_marker_score(self, directory: Path, files: list[dict[str, Any]]) -> int:
        score = 0
        names = {path.name for path in directory.iterdir()} if directory.exists() else set()
        score += sum(1 for marker in SERVICE_MARKER_FILES if marker in names)
        if any(keyword in directory.name.lower() for keyword in API_KEYWORDS):
            score += 1
        score += sum(1 for item in files if self._normalize_items(item.get("apis")))
        return score

    def _top_level_directories(self, repository_root: Path) -> list[Path]:
        return [path for path in sorted(repository_root.iterdir()) if path.is_dir()]

    def _normalize_items(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _normalize_strings(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]

    def _node_id(self, value: str) -> str:
        chars = [char if char.isalnum() else "_" for char in value]
        return "n_" + "".join(chars).strip("_")

    def _label(self, value: str) -> str:
        return value.replace('"', "'")
