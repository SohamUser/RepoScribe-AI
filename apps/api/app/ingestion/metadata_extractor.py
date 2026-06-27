from collections import Counter
from pathlib import Path

from app.schemas.repository import FileTreeNode, RepositoryMetadataResponse

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    ".venv",
    "venv",
}

IGNORED_EXTENSIONS = {
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".pyc",
    ".pyo",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".h": "C",
    ".hpp": "C++",
    ".m": "Objective-C",
    ".scala": "Scala",
}

PACKAGE_MANAGER_FILES = {
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "bun.lock": "bun",
    "poetry.lock": "poetry",
    "Pipfile.lock": "pipenv",
    "requirements.txt": "pip",
    "uv.lock": "uv",
    "go.mod": "go modules",
    "Cargo.lock": "cargo",
    "Gemfile.lock": "bundler",
    "composer.lock": "composer",
}

FRAMEWORK_MARKERS = {
    "next.config.js": "Next.js",
    "next.config.ts": "Next.js",
    "nuxt.config.ts": "Nuxt",
    "nuxt.config.js": "Nuxt",
    "manage.py": "Django",
    "angular.json": "Angular",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "svelte.config.js": "SvelteKit",
    "svelte.config.ts": "SvelteKit",
    "Cargo.toml": "Rust",
}


class RepositoryMetadataExtractor:
    def extract(self, repository_root: Path, repository_url: str, owner: str, branch: str) -> RepositoryMetadataResponse:
        language_counts: Counter[str] = Counter()
        package_managers: set[str] = set()
        frameworks: set[str] = set()
        file_tree: list[FileTreeNode] = []

        for path in self._iter_paths(repository_root):
            relative_path = path.relative_to(repository_root).as_posix()
            if path.is_dir():
                file_tree.append(FileTreeNode(path=relative_path, type="directory"))
                continue

            file_tree.append(FileTreeNode(path=relative_path, type="file"))
            suffix = path.suffix.lower()
            language = LANGUAGE_BY_EXTENSION.get(suffix)
            if language:
                language_counts[language] += 1

            package_manager = PACKAGE_MANAGER_FILES.get(path.name)
            if package_manager:
                package_managers.add(package_manager)

            framework = FRAMEWORK_MARKERS.get(path.name)
            if framework:
                frameworks.add(framework)

            self._detect_framework_from_contents(path, frameworks)

        repository_name = repository_root.name
        languages = [language for language, _ in language_counts.most_common()]

        return RepositoryMetadataResponse(
            repository_url=repository_url,
            repository_name=repository_name,
            owner=owner,
            branch=branch,
            languages=languages,
            package_managers=sorted(package_managers),
            frameworks=sorted(frameworks),
            file_tree=file_tree,
        )

    def _iter_paths(self, repository_root: Path):
        for path in sorted(repository_root.rglob("*")):
            if self._should_skip(path, repository_root):
                continue
            yield path

    def _should_skip(self, path: Path, repository_root: Path) -> bool:
        relative_parts = path.relative_to(repository_root).parts
        if any(part in IGNORED_DIRECTORIES for part in relative_parts):
            return True
        if path.is_file() and path.suffix.lower() in IGNORED_EXTENSIONS:
            return True
        return False

    def _detect_framework_from_contents(self, path: Path, frameworks: set[str]) -> None:
        if path.name == "package.json":
            text = path.read_text(encoding="utf-8", errors="ignore")
            checks = {
                "\"next\"": "Next.js",
                "\"react\"": "React",
                "\"vue\"": "Vue",
                "\"@angular/core\"": "Angular",
                "\"svelte\"": "Svelte",
                "\"nuxt\"": "Nuxt",
                "\"nestjs\"": "NestJS",
                "\"express\"": "Express",
            }
            for marker, framework in checks.items():
                if marker in text:
                    frameworks.add(framework)
        elif path.name == "pyproject.toml":
            text = path.read_text(encoding="utf-8", errors="ignore")
            checks = {
                "fastapi": "FastAPI",
                "django": "Django",
                "flask": "Flask",
            }
            for marker, framework in checks.items():
                if marker in text.lower():
                    frameworks.add(framework)
        elif path.name == "requirements.txt":
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "fastapi" in text:
                frameworks.add("FastAPI")
            if "django" in text:
                frameworks.add("Django")
            if "flask" in text:
                frameworks.add("Flask")
