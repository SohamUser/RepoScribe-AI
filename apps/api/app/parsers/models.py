from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SourceLocation:
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(slots=True)
class ImportReference:
    module: str
    names: list[str] = field(default_factory=list)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"module": self.module, "names": self.names}
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class ExportReference:
    name: str
    kind: str
    is_default: bool = False
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "kind": self.kind,
            "is_default": self.is_default,
        }
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class FunctionSymbol:
    name: str
    signature: str
    is_async: bool
    parameters: list[str]
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "signature": self.signature,
            "is_async": self.is_async,
            "parameters": self.parameters,
        }
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class ClassSymbol:
    name: str
    kind: str
    bases: list[str]
    methods: list[str]
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "kind": self.kind,
            "bases": self.bases,
            "methods": self.methods,
        }
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class ApiReference:
    name: str
    method: str
    route: str
    source: str
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "method": self.method,
            "route": self.route,
            "source": self.source,
        }
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class CommentReference:
    text: str
    kind: str
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"text": self.text, "kind": self.kind}
        if self.location is not None:
            payload["location"] = self.location.to_dict()
        return payload


@dataclass(slots=True)
class ParsedFile:
    path: str
    language: str
    ast_root_type: str
    node_count: int
    imports: list[ImportReference]
    exports: list[ExportReference]
    functions: list[FunctionSymbol]
    classes: list[ClassSymbol]
    apis: list[ApiReference]
    comments: list[CommentReference]
    dependencies: list[str]
    llm_outline: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "language": self.language,
            "ast_root_type": self.ast_root_type,
            "node_count": self.node_count,
            "imports": [item.to_dict() for item in self.imports],
            "exports": [item.to_dict() for item in self.exports],
            "functions": [item.to_dict() for item in self.functions],
            "classes": [item.to_dict() for item in self.classes],
            "apis": [item.to_dict() for item in self.apis],
            "comments": [item.to_dict() for item in self.comments],
            "dependencies": self.dependencies,
            "llm_outline": self.llm_outline,
        }


@dataclass(slots=True)
class ParsedRepository:
    repository_path: str
    files: list[ParsedFile]
    languages: list[str]
    stats: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_path": self.repository_path,
            "languages": self.languages,
            "stats": self.stats,
            "files": [item.to_dict() for item in self.files],
        }


def relative_path(root: Path, file_path: Path) -> str:
    return file_path.relative_to(root).as_posix()
