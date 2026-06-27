import re

from tree_sitter import Language

from app.parsers.base import BaseLanguageParser, ParserConfig, load_language_from_module
from app.parsers.models import ApiReference, ExportReference, FunctionSymbol

API_PATTERN = re.compile(
    r"@(?P<method>GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)\((?P<args>[^\)]*)\)",
    re.MULTILINE,
)
ROUTE_PATTERN = re.compile(r'["\'](?P<route>/[^"\']*)["\']')
HTTP_METHOD_PATTERN = re.compile(r"RequestMethod\.(?P<method>GET|POST|PUT|PATCH|DELETE)")


class JavaParser(BaseLanguageParser):
    def __init__(self) -> None:
        super().__init__(
            ParserConfig(
                language_name="Java",
                extensions=(".java",),
                function_nodes={"method_declaration", "constructor_declaration"},
                class_nodes={"class_declaration"},
                import_nodes={"import_declaration"},
                export_nodes=set(),
                comment_nodes={"line_comment", "block_comment"},
                method_nodes={"method_declaration", "constructor_declaration"},
                interface_nodes={"interface_declaration"},
            )
        )

    def load_language(self) -> Language:
        return load_language_from_module("tree_sitter_java", ("language",))

    def detect_api_patterns(
        self,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        function_names = [item.name for item in functions]
        results: list[ApiReference] = []
        for index, match in enumerate(API_PATTERN.finditer(text)):
            route_match = ROUTE_PATTERN.search(match.group("args"))
            http_method_match = HTTP_METHOD_PATTERN.search(match.group("args"))
            http_method = match.group("method").replace("Mapping", "").upper()
            if http_method == "REQUEST":
                http_method = http_method_match.group("method") if http_method_match else "GET"
            results.append(
                ApiReference(
                    name=function_names[index] if index < len(function_names) else match.group("method"),
                    method=http_method,
                    route=route_match.group("route") if route_match else "/",
                    source="spring-annotation",
                )
            )
        return results

    def infer_exports(self, root, source_bytes, functions, classes):  # type: ignore[override]
        text = source_bytes.decode("utf-8", errors="ignore")
        exports: list[ExportReference] = []
        if "public class" in text or "public interface" in text:
            for item in classes:
                exports.append(ExportReference(name=item.name, kind="public-type"))
        for item in functions:
            if f"public {item.name}" in text or f"public static {item.name}" in text:
                exports.append(ExportReference(name=item.name, kind="public-method"))
        return exports
