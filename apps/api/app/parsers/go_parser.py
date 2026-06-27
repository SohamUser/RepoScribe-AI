import re

from tree_sitter import Language, Node

from app.parsers.base import BaseLanguageParser, ParserConfig, load_language_from_module
from app.parsers.models import ApiReference, ExportReference, FunctionSymbol, ImportReference

IMPORT_PATTERN = re.compile(r'"(?P<module>[^"]+)"')
API_PATTERN = re.compile(
    r"(?P<source>\b(?:router|r|engine|http)\b)\.(?P<method>GET|POST|PUT|PATCH|DELETE|HandleFunc)\(\s*\"(?P<route>[^\"]+)\"",
    re.IGNORECASE,
)


class GoParser(BaseLanguageParser):
    def __init__(self) -> None:
        super().__init__(
            ParserConfig(
                language_name="Go",
                extensions=(".go",),
                function_nodes={"function_declaration", "method_declaration"},
                class_nodes={"type_declaration"},
                import_nodes={"import_declaration", "import_spec"},
                export_nodes=set(),
                comment_nodes={"comment"},
                method_nodes={"method_declaration"},
            )
        )

    def load_language(self) -> Language:
        return load_language_from_module("tree_sitter_go", ("language",))

    def parse_import_node(self, node: Node, source_bytes: bytes) -> ImportReference | None:
        text = self.node_text(node, source_bytes)
        match = IMPORT_PATTERN.search(text)
        if not match:
            return None
        return ImportReference(module=match.group("module"), location=self.node_location(node))

    def detect_api_patterns(
        self,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        function_names = {item.name for item in functions}
        results: list[ApiReference] = []
        for match in API_PATTERN.finditer(text):
            method = "GET" if match.group("method").lower() == "handlefunc" else match.group("method").upper()
            results.append(
                ApiReference(
                    name=next(iter(function_names), match.group("source")),
                    method=method,
                    route=match.group("route"),
                    source=match.group("source"),
                )
            )
        return results

    def infer_exports(self, root, source_bytes, functions, classes):  # type: ignore[override]
        exports: list[ExportReference] = []
        for item in functions:
            if item.name[:1].isupper():
                exports.append(ExportReference(name=item.name, kind="public-function"))
        for item in classes:
            if item.name[:1].isupper():
                exports.append(ExportReference(name=item.name, kind="public-type"))
        return exports
