import re

from tree_sitter import Language

from app.parsers.base import BaseLanguageParser, ParserConfig, load_language_from_module
from app.parsers.models import ApiReference, ExportReference, FunctionSymbol, ImportReference

IMPORT_PATTERN = re.compile(
    r"^\s*(?:from\s+(?P<from>[\w\.]+)\s+import|import\s+(?P<import>[\w\.,\s]+))",
    re.MULTILINE,
)
API_PATTERN = re.compile(
    r"@(?P<source>[\w\.]+)\.(?P<method>get|post|put|patch|delete|options|head)\(\s*[frbuFRBU]*['\"](?P<route>[^'\"]+)['\"]",
    re.IGNORECASE,
)
ALL_PATTERN = re.compile(r"__all__\s*=\s*\[(?P<values>[^\]]+)\]")


class PythonParser(BaseLanguageParser):
    def __init__(self) -> None:
        super().__init__(
            ParserConfig(
                language_name="Python",
                extensions=(".py",),
                function_nodes={"function_definition", "async_function_definition"},
                class_nodes={"class_definition"},
                import_nodes={"import_statement", "import_from_statement"},
                export_nodes=set(),
                comment_nodes={"comment"},
            )
        )

    def load_language(self) -> Language:
        return load_language_from_module("tree_sitter_python", ("language",))

    def extra_imports_from_source(self, source_bytes: bytes) -> list[ImportReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        imports: list[ImportReference] = []
        for match in IMPORT_PATTERN.finditer(text):
            if match.group("from"):
                imports.append(ImportReference(module=match.group("from")))
            elif match.group("import"):
                for item in match.group("import").split(","):
                    imports.append(ImportReference(module=item.strip().split(" as ")[0].strip()))
        return imports

    def detect_api_patterns(
        self,
        source_bytes: bytes,
        functions: list[FunctionSymbol],
    ) -> list[ApiReference]:
        text = source_bytes.decode("utf-8", errors="ignore")
        function_names = [item.name for item in functions]
        results: list[ApiReference] = []
        for index, match in enumerate(API_PATTERN.finditer(text)):
            name = function_names[index] if index < len(function_names) else match.group("source")
            results.append(
                ApiReference(
                    name=name,
                    method=match.group("method").upper(),
                    route=match.group("route"),
                    source=match.group("source"),
                )
            )
        return results

    def infer_exports(self, root, source_bytes, functions, classes):  # type: ignore[override]
        text = source_bytes.decode("utf-8", errors="ignore")
        exports: list[ExportReference] = []
        match = ALL_PATTERN.search(text)
        if match:
            values = [value.strip().strip("'\"") for value in match.group("values").split(",") if value.strip()]
            for value in values:
                exports.append(ExportReference(name=value, kind="__all__"))
        return exports
