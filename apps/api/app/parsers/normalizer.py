from collections import Counter
from pathlib import Path

from app.parsers.models import ParsedFile, ParsedRepository, relative_path


class ASTNormalizer:
    def normalize_repository(self, repository_root: Path, files: list[ParsedFile]) -> ParsedRepository:
        languages = sorted({parsed.language for parsed in files})
        stats = self._build_stats(files)

        normalized_files: list[ParsedFile] = []
        for parsed in files:
            normalized_files.append(
                ParsedFile(
                    path=relative_path(repository_root, Path(parsed.path)),
                    language=parsed.language,
                    ast_root_type=parsed.ast_root_type,
                    node_count=parsed.node_count,
                    imports=parsed.imports,
                    exports=parsed.exports,
                    functions=parsed.functions,
                    classes=parsed.classes,
                    apis=parsed.apis,
                    comments=parsed.comments,
                    dependencies=parsed.dependencies,
                    llm_outline=parsed.llm_outline,
                )
            )

        return ParsedRepository(
            repository_path=repository_root.as_posix(),
            files=normalized_files,
            languages=languages,
            stats=stats,
        )

    def _build_stats(self, files: list[ParsedFile]) -> dict[str, int]:
        counters = Counter[str]()
        counters["file_count"] = len(files)
        counters["file_count_estimate"] = len(files)
        counters["function_count"] = sum(len(item.functions) for item in files)
        counters["class_count"] = sum(len(item.classes) for item in files)
        counters["import_count"] = sum(len(item.imports) for item in files)
        counters["export_count"] = sum(len(item.exports) for item in files)
        counters["api_count"] = sum(len(item.apis) for item in files)
        counters["comment_count"] = sum(len(item.comments) for item in files)
        return dict(counters)
