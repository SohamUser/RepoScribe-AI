import re

from tree_sitter import Language, Node

from app.parsers.base import BaseLanguageParser, ParserConfig, load_language_from_module
from app.parsers.models import ApiReference, ExportReference, FunctionSymbol, ImportReference

API_PATTERN = re.compile(
    r"(?P<source>\b(?:app|router)\b)\.(?P<method>get|post|put|patch|delete|options|head)\(\s*['\"](?P<route>[^'\"]+)['\"]",
    re.IGNORECASE,
)
REQUIRE_PATTERN = re.compile(r"require\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)")


class JavaScriptParser(BaseLanguageParser):
    def __init__(self) -> None:
        super().__init__(
            ParserConfig(
                language_name="JavaScript",
                extensions=(".js", ".jsx", ".mjs", ".cjs"),
                function_nodes={"function_declaration", "arrow_function", "function"},
                class_nodes={"class_declaration"},
                import_nodes={"import_statement"},
                export_nodes={"export_statement"},
                comment_nodes={"comment"},
                method_nodes={"method_definition"},
            )
        )

    def load_language(self) -> Language:
        return load_language_from_module("tree_sitter_javascript", ("language",))

    def extra_imports_from_source(self, source_bytes: bytes) -> list[ImportReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        return [ImportReference(module=match.group("module")) for match in REQUIRE_PATTERN.finditer(text)]

    def detect_api_patterns(
        self,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        function_names = {item.name for item in functions}
        results: list[ApiReference] = []
        for match in API_PATTERN.finditer(text):
            results.append(
                ApiReference(
                    name=next(iter(function_names), match.group("source")),
                    method=match.group("method").upper(),
                    route=match.group("route"),
                    source=match.group("source"),
                )
            )
        return results

    def parse_export_node(self, node: Node, source_bytes: bytes) -> ExportReference | None:
        text = self.node_text(node, source_bytes)
        name = self.extract_symbol_name(node, source_bytes) or ("default" if "default" in text else "anonymous")
        return ExportReference(
            name=name,
            kind="export",
            is_default="default" in text,
            location=self.node_location(node),
        )
