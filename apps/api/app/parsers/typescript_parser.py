import re

from tree_sitter import Language

from app.parsers.base import BaseLanguageParser, ParserConfig, load_language_from_module
from app.parsers.models import ApiReference, ExportReference, FunctionSymbol, ImportReference

API_PATTERN = re.compile(
    r"(?P<source>\b(?:app|router)\b)\.(?P<method>get|post|put|patch|delete|options|head)\(\s*['\"](?P<route>[^'\"]+)['\"]",
    re.IGNORECASE,
)
NEXT_HANDLER_PATTERN = re.compile(r"export\s+(?:async\s+)?function\s+(?P<method>GET|POST|PUT|PATCH|DELETE)")
REQUIRE_PATTERN = re.compile(r"require\(\s*['\"](?P<module>[^'\"]+)['\"]\s*\)")


class TypeScriptParser(BaseLanguageParser):
    def __init__(self) -> None:
        super().__init__(
            ParserConfig(
                language_name="TypeScript",
                extensions=(".ts", ".tsx"),
                function_nodes={
                    "function_declaration",
                    "arrow_function",
                    "function",
                    "generator_function_declaration",
                },
                class_nodes={"class_declaration"},
                import_nodes={"import_statement"},
                export_nodes={"export_statement"},
                comment_nodes={"comment"},
                method_nodes={"method_definition", "abstract_method_signature"},
                interface_nodes={"interface_declaration"},
            )
        )

    def load_language(self) -> Language:
        return load_language_from_module(
            "tree_sitter_typescript",
            ("language_typescript", "typescript", "language"),
        )

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
        for match in NEXT_HANDLER_PATTERN.finditer(text):
            results.append(
                ApiReference(
                    name=match.group("method"),
                    method=match.group("method"),
                    route="/",
                    source="next-route-handler",
                )
            )
        return results

    def infer_exports(self, root, source_bytes, functions, classes):  # type: ignore[override]
        exports = super().infer_exports(root, source_bytes, functions, classes)
        for item in functions:
            if item.name.isupper():
                exports.append(ExportReference(name=item.name, kind="named-export"))
        return exports
