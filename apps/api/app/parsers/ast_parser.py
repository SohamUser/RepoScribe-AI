from pathlib import Path

from app.ingestion.metadata_extractor import IGNORED_DIRECTORIES, IGNORED_EXTENSIONS
from app.parsers.normalizer import ASTNormalizer
from app.parsers.registry import ParserRegistry


class ASTParser:
    def __init__(self) -> None:
        self.registry = ParserRegistry()
        self.normalizer = ASTNormalizer()

    def parse_repository(self, repository_root: Path) -> dict[str, object]:
        parsed_files = self._parse_paths(
            repository_root=repository_root,
            file_paths=[path for path in sorted(repository_root.rglob("*")) if path.is_file()],
        )
        return self.normalizer.normalize_repository(repository_root, parsed_files).to_dict()

    def parse_files(self, repository_root: Path, file_paths: list[Path]) -> dict[str, object]:
        parsed_files = self._parse_paths(repository_root=repository_root, file_paths=sorted(file_paths))
        return self.normalizer.normalize_repository(repository_root, parsed_files).to_dict()

    def _parse_paths(self, repository_root: Path, file_paths: list[Path]):
        parsed_files = []
        for file_path in file_paths:
            if self._should_skip(file_path, repository_root):
                continue
            if not self.registry.supports(file_path):
                continue
            parser = self.registry.get_for_file(file_path)
            parsed_files.append(parser.parse_file(file_path))
        return parsed_files

    def _should_skip(self, file_path: Path, repository_root: Path) -> bool:
        relative_parts = file_path.relative_to(repository_root).parts
        if any(part in IGNORED_DIRECTORIES for part in relative_parts):
            return True
        if file_path.suffix.lower() in IGNORED_EXTENSIONS:
            return True
        return False
