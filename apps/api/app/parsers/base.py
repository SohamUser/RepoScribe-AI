from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Parser

from app.core.errors import AppError
from app.parsers.models import (
    ApiReference,
    ClassSymbol,
    CommentReference,
    ExportReference,
    FunctionSymbol,
    ImportReference,
    ParsedFile,
    SourceLocation,
)


@dataclass(slots=True)
class ParserConfig:
    language_name: str
    extensions: tuple[str, ...]
    function_nodes: set[str]
    class_nodes: set[str]
    import_nodes: set[str]
    export_nodes: set[str]
    comment_nodes: set[str]
    method_nodes: set[str] = field(default_factory=set)
    interface_nodes: set[str] = field(default_factory=set)
    identifier_nodes: set[str] = field(
        default_factory=lambda: {
            "identifier",
            "property_identifier",
            "type_identifier",
            "field_identifier",
            "shorthand_property_identifier",
            "scoped_identifier",
        }
    )


class BaseLanguageParser(ABC):
    def __init__(self, config: ParserConfig):
        self.config = config
        self.parser = Parser(self.load_language())

    @abstractmethod
    def load_language(self) -> Language:
        raise NotImplementedError

    def parse_file(self, file_path: Path) -> ParsedFile:
        source_bytes = file_path.read_bytes()
        tree = self.parser.parse(source_bytes)
        root = tree.root_node

        imports = self.extract_imports(root, source_bytes)
        functions = self.extract_functions(root, source_bytes)
        classes = self.extract_classes(root, source_bytes)
        exports = self.extract_exports(root, source_bytes, functions, classes)
        comments = self.extract_comments(root, source_bytes)
        apis = self.extract_apis(root, source_bytes, functions)
        dependencies = sorted({item.module for item in imports if item.module})

        return ParsedFile(
            path=file_path.as_posix(),
            language=self.config.language_name,
            ast_root_type=root.type,
            node_count=self.count_nodes(root),
            imports=imports,
            exports=exports,
            functions=functions,
            classes=classes,
            apis=apis,
            comments=comments,
            dependencies=dependencies,
            llm_outline=self.build_llm_outline(file_path, imports, functions, classes, apis),
        )

    def extract_imports(self, root: Node, source_bytes: bytes) -> list[ImportReference]:
        imports: list[ImportReference] = []
        for node in self.iter_nodes(root):
            if node.type in self.config.import_nodes:
                parsed = self.parse_import_node(node, source_bytes)
                if parsed is not None:
                    imports.append(parsed)
        imports.extend(self.extra_imports_from_source(source_bytes))
        return self._unique_imports(imports)

    def extract_functions(self, root: Node, source_bytes: bytes) -> list[FunctionSymbol]:
        functions: list[FunctionSymbol] = []
        for node in self.iter_nodes(root):
            if node.type in self.config.function_nodes or node.type in self.config.method_nodes:
                name = self.extract_symbol_name(node, source_bytes)
                if not name:
                    continue
                parameters_node = node.child_by_field_name("parameters")
                parameters = self.extract_parameters(parameters_node, source_bytes)
                functions.append(
                    FunctionSymbol(
                        name=name,
                        signature=self.node_text(node, source_bytes).split("{", 1)[0].strip(),
                        is_async="async" in node.type or self.node_text(node, source_bytes).lstrip().startswith("async "),
                        parameters=parameters,
                        location=self.node_location(node),
                    )
                )
        return self._dedupe_by_name(functions)

    def extract_classes(self, root: Node, source_bytes: bytes) -> list[ClassSymbol]:
        classes: list[ClassSymbol] = []
        for node in self.iter_nodes(root):
            if node.type in self.config.class_nodes or node.type in self.config.interface_nodes:
                name = self.extract_symbol_name(node, source_bytes)
                if not name:
                    continue
                methods = [
                    self.extract_symbol_name(child, source_bytes)
                    for child in self.iter_nodes(node)
                    if child.type in self.config.method_nodes
                ]
                classes.append(
                    ClassSymbol(
                        name=name,
                        kind="interface" if node.type in self.config.interface_nodes else "class",
                        bases=self.extract_bases(node, source_bytes),
                        methods=[method for method in methods if method],
                        location=self.node_location(node),
                    )
                )
        return self._dedupe_by_name(classes)

    def extract_exports(
        self,
        root: Node,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
        classes: list[ClassSymbol],
    ) -> list[ExportReference]:
        exports: list[ExportReference] = []
        for node in self.iter_nodes(root):
            if node.type in self.config.export_nodes:
                parsed = self.parse_export_node(node, source_bytes)
                if parsed is not None:
                    exports.append(parsed)
        exports.extend(self.infer_exports(root, source_bytes, functions, classes))
        return self._unique_exports(exports)

    def extract_comments(self, root: Node, source_bytes: bytes) -> list[CommentReference]:
        comments: list[CommentReference] = []
        for node in self.iter_nodes(root):
            if node.type in self.config.comment_nodes or "comment" in node.type:
                text = self.node_text(node, source_bytes).strip()
                if text:
                    comments.append(
                        CommentReference(
                            text=text,
                            kind=node.type,
                            location=self.node_location(node),
                        )
                    )
        return comments

    def extract_apis(
        self,
        root: Node,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        return self.detect_api_patterns(source_bytes, functions)

    def build_llm_outline(
        self,
        file_path: Path,
        imports: list[ImportReference],
        functions: list[FunctionSymbol],
        classes: list[ClassSymbol],
        apis: list[ApiReference],
    ) -> list[str]:
        outline = [f"File: {file_path.name} [{self.config.language_name}]"]
        if imports:
            outline.append("Imports: " + ", ".join(item.module for item in imports[:8]))
        if functions:
            outline.append("Functions: " + ", ".join(item.name for item in functions[:8]))
        if classes:
            outline.append("Classes: " + ", ".join(item.name for item in classes[:8]))
        if apis:
            outline.append(
                "APIs: " + ", ".join(f"{item.method} {item.route}" for item in apis[:8])
            )
        return outline

    def parse_import_node(self, node: Node, source_bytes: bytes) -> ImportReference | None:
        text = self.node_text(node, source_bytes)
        module = self.extract_quoted_value(text)
        if not module:
            return None
        names = self.extract_named_identifiers(node, source_bytes)
        return ImportReference(module=module, names=names, location=self.node_location(node))

    def parse_export_node(self, node: Node, source_bytes: bytes) -> ExportReference | None:
        text = self.node_text(node, source_bytes)
        name = self.extract_symbol_name(node, source_bytes)
        if not name:
            name = "default" if "default" in text else text.splitlines()[0][:80]
        return ExportReference(
            name=name,
            kind=node.type,
            is_default="default" in text,
            location=self.node_location(node),
        )

    def infer_exports(
        self,
        root: Node,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
        classes: list[ClassSymbol],
    ) -> list[ExportReference]:
        _ = (root, source_bytes, functions, classes)
        return []

    def extra_imports_from_source(self, source_bytes: bytes) -> list[ImportReference]:
        _ = source_bytes
        return []

    def detect_api_patterns(
        self,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        _ = (source_bytes, functions)
        return []

    def extract_bases(self, node: Node, source_bytes: bytes) -> list[str]:
        candidates = []
        for field_name in ("superclass", "super_interfaces", "bases", "extends", "implements"):
            field = node.child_by_field_name(field_name)
            if field is not None:
                candidates.append(self.node_text(field, source_bytes).strip())
        return [item for item in candidates if item]

    def extract_parameters(self, node: Node | None, source_bytes: bytes) -> list[str]:
        if node is None:
            return []
        values: list[str] = []
        for child in node.named_children:
            text = self.node_text(child, source_bytes).strip()
            if text:
                values.append(text)
        return values

    def extract_symbol_name(self, node: Node, source_bytes: bytes) -> str | None:
        for field_name in ("name", "declarator", "alias", "function", "type", "left"):
            field = node.child_by_field_name(field_name)
            if field is not None:
                identifier = self.find_identifier(field, source_bytes)
                if identifier:
                    return identifier
        return self.find_identifier(node, source_bytes)

    def find_identifier(self, node: Node, source_bytes: bytes) -> str | None:
        if node.type in self.config.identifier_nodes:
            return self.node_text(node, source_bytes).strip()
        for child in node.named_children:
            identifier = self.find_identifier(child, source_bytes)
            if identifier:
                return identifier
        return None

    def extract_named_identifiers(self, node: Node, source_bytes: bytes) -> list[str]:
        values: list[str] = []
        for child in self.iter_nodes(node):
            if child.type in self.config.identifier_nodes:
                text = self.node_text(child, source_bytes).strip()
                if text:
                    values.append(text)
        return list(dict.fromkeys(values))

    def extract_quoted_value(self, text: str) -> str:
        for quote in ("'", '"', "`"):
            if quote in text:
                parts = text.split(quote)
                if len(parts) >= 3:
                    return parts[1].strip()
        return ""

    def node_text(self, node: Node, source_bytes: bytes) -> str:
        return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")

    def node_location(self, node: Node) -> SourceLocation:
        return SourceLocation(
            start_line=node.start_point[0] + 1,
            start_column=node.start_point[1] + 1,
            end_line=node.end_point[0] + 1,
            end_column=node.end_point[1] + 1,
        )

    def count_nodes(self, root: Node) -> int:
        return sum(1 for _ in self.iter_nodes(root))

    def iter_nodes(self, node: Node):
        yield node
        for child in node.children:
            yield from self.iter_nodes(child)

    def _dedupe_by_name(self, items: list[Any]) -> list[Any]:
        seen: set[str] = set()
        result: list[Any] = []
        for item in items:
            name = getattr(item, "name", None)
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(item)
        return result

    def _unique_imports(self, items: list[ImportReference]) -> list[ImportReference]:
        seen: set[tuple[str, tuple[str, ...]]] = set()
        result: list[ImportReference] = []
        for item in items:
            key = (item.module, tuple(item.names))
            if item.module and key not in seen:
                seen.add(key)
                result.append(item)
        return result

    def _unique_exports(self, items: list[ExportReference]) -> list[ExportReference]:
        seen: set[tuple[str, str, bool]] = set()
        result: list[ExportReference] = []
        for item in items:
            key = (item.name, item.kind, item.is_default)
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result


def load_language_from_module(module_name: str, attribute_candidates: tuple[str, ...]) -> Language:
    try:
        module = __import__(module_name)
    except ImportError as exc:
        raise AppError(
            message=f"Missing parser dependency for {module_name}. Install the Tree-sitter language package.",
            code="parser_dependency_missing",
        ) from exc

    for attribute_name in attribute_candidates:
        attribute = getattr(module, attribute_name, None)
        if attribute is None:
            continue
        raw_language = attribute() if callable(attribute) else attribute
        if isinstance(raw_language, Language):
            return raw_language
        return Language(raw_language)

    raise AppError(
        message=f"Could not load Tree-sitter language from {module_name}.",
        code="parser_language_load_failed",
    )
