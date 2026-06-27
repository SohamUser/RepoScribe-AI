from pathlib import Path

from app.core.errors import AppError
from app.parsers.go_parser import GoParser
from app.parsers.java_parser import JavaParser
from app.parsers.javascript_parser import JavaScriptParser
from app.parsers.python_parser import PythonParser
from app.parsers.typescript_parser import TypeScriptParser
from app.parsers.base import BaseLanguageParser


class ParserRegistry:
    def __init__(self) -> None:
        self.parsers = [
            TypeScriptParser(),
            JavaScriptParser(),
            PythonParser(),
            GoParser(),
            JavaParser(),
        ]
        self._by_extension = {
            extension: parser
            for parser in self.parsers
            for extension in parser.config.extensions
        }

    def get_for_file(self, file_path: Path) -> BaseLanguageParser:
        parser = self._by_extension.get(file_path.suffix.lower())
        if parser is None:
            raise AppError(
                message=f"Unsupported source file type: {file_path.suffix}",
                code="unsupported_language",
            )
        return parser

    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self._by_extension
