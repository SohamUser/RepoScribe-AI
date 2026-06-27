from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChunkMetadata:
    chunk_id: str
    file_path: str
    language: str
    module_type: str
    chunk_type: str
    symbol_name: str | None
    dependencies: list[str]
    source_ref: str
    related_symbols: list[str]
    api_routes: list[str]
    start_line: int | None
    end_line: int | None
    part_index: int = 1
    part_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "language": self.language,
            "module_type": self.module_type,
            "chunk_type": self.chunk_type,
            "symbol_name": self.symbol_name,
            "dependencies": self.dependencies,
            "source_ref": self.source_ref,
            "related_symbols": self.related_symbols,
            "api_routes": self.api_routes,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "part_index": self.part_index,
            "part_count": self.part_count,
        }


@dataclass(slots=True)
class EmbeddingChunk:
    chunk_id: str
    text: str
    metadata: ChunkMetadata

    def to_dict(self) -> dict[str, Any]:
        payload = self.metadata.to_dict()
        payload["text_length"] = len(self.text)
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "metadata": payload,
        }


class CodeChunkingEngine:
    def __init__(self, max_chunk_chars: int = 1800) -> None:
        self.max_chunk_chars = max_chunk_chars

    def build_chunks(
        self,
        repository_root: Path,
        parsed_repository: dict[str, Any],
    ) -> list[dict[str, Any]]:
        chunks: list[EmbeddingChunk] = []
        for file_payload in parsed_repository.get("files", []):
            if not isinstance(file_payload, dict):
                continue
            chunks.extend(self._build_file_chunks(repository_root, file_payload))
        return [chunk.to_dict() for chunk in chunks]

    def _build_file_chunks(
        self,
        repository_root: Path,
        file_payload: dict[str, Any],
    ) -> list[EmbeddingChunk]:
        file_path = str(file_payload.get("path", ""))
        if not file_path:
            return []

        source_path = repository_root / file_path
        if not source_path.exists():
            return []

        source_text = source_path.read_text(encoding="utf-8", errors="ignore")
        source_lines = source_text.splitlines()
        language = str(file_payload.get("language", "unknown"))
        dependencies = self._normalize_string_list(file_payload.get("dependencies"))
        functions = self._normalize_items(file_payload.get("functions"))
        classes = self._normalize_items(file_payload.get("classes"))
        apis = self._normalize_items(file_payload.get("apis"))
        exports = self._normalize_items(file_payload.get("exports"))
        module_type = self._infer_module_type(file_path, classes, apis)

        chunks: list[EmbeddingChunk] = []
        module_summary = self._build_module_summary(
            file_path=file_path,
            language=language,
            module_type=module_type,
            dependencies=dependencies,
            functions=functions,
            classes=classes,
            apis=apis,
            exports=exports,
            file_payload=file_payload,
            source_text=source_text,
        )
        chunks.extend(
            self._make_chunks(
                file_path=file_path,
                language=language,
                module_type=module_type,
                chunk_type="module",
                symbol_name=None,
                dependencies=dependencies,
                related_symbols=[item["name"] for item in functions[:6] if item.get("name")],
                api_routes=[self._format_route(item) for item in apis[:6]],
                body=module_summary,
                start_line=1,
                end_line=max(len(source_lines), 1),
            )
        )

        for class_item in classes:
            name = str(class_item.get("name", "")).strip()
            location = self._extract_location(class_item)
            if not name or location is None:
                continue
            class_body = self._slice_source(source_lines, location["start_line"], location["end_line"])
            related = self._normalize_string_list(class_item.get("methods"))
            chunks.extend(
                self._make_chunks(
                    file_path=file_path,
                    language=language,
                    module_type=module_type,
                    chunk_type="class",
                    symbol_name=name,
                    dependencies=dependencies,
                    related_symbols=related,
                    api_routes=[],
                    body=class_body,
                    start_line=location["start_line"],
                    end_line=location["end_line"],
                )
            )

        for function_item in functions:
            name = str(function_item.get("name", "")).strip()
            location = self._extract_location(function_item)
            if not name or location is None:
                continue
            function_body = self._slice_source(source_lines, location["start_line"], location["end_line"])
            related_routes = [
                self._format_route(api_item)
                for api_item in apis
                if str(api_item.get("name", "")).strip() == name
            ]
            chunks.extend(
                self._make_chunks(
                    file_path=file_path,
                    language=language,
                    module_type=module_type,
                    chunk_type="function",
                    symbol_name=name,
                    dependencies=dependencies,
                    related_symbols=self._related_class_names(name, classes),
                    api_routes=related_routes,
                    body=function_body,
                    start_line=location["start_line"],
                    end_line=location["end_line"],
                )
            )

        for api_item in apis:
            name = str(api_item.get("name", "")).strip()
            method = str(api_item.get("method", "")).strip()
            route = str(api_item.get("route", "")).strip()
            if not name or not route:
                continue
            matching_function = next(
                (item for item in functions if str(item.get("name", "")).strip() == name),
                None,
            )
            location = self._extract_location(matching_function) if matching_function else None
            route_body = ""
            start_line = None
            end_line = None
            if location is not None:
                route_body = self._slice_source(source_lines, location["start_line"], location["end_line"])
                start_line = location["start_line"]
                end_line = location["end_line"]
            else:
                route_body = f"{method} {route}\nHandler: {name}"
            chunks.extend(
                self._make_chunks(
                    file_path=file_path,
                    language=language,
                    module_type=module_type,
                    chunk_type="route",
                    symbol_name=name,
                    dependencies=dependencies,
                    related_symbols=[name],
                    api_routes=[self._format_route(api_item)],
                    body=route_body,
                    start_line=start_line,
                    end_line=end_line,
                )
            )

        return chunks

    def _build_module_summary(
        self,
        *,
        file_path: str,
        language: str,
        module_type: str,
        dependencies: list[str],
        functions: list[dict[str, Any]],
        classes: list[dict[str, Any]],
        apis: list[dict[str, Any]],
        exports: list[dict[str, Any]],
        file_payload: dict[str, Any],
        source_text: str,
    ) -> str:
        outline = self._normalize_string_list(file_payload.get("llm_outline"))
        function_names = [str(item.get("name", "")).strip() for item in functions if item.get("name")]
        class_names = [str(item.get("name", "")).strip() for item in classes if item.get("name")]
        export_names = [str(item.get("name", "")).strip() for item in exports if item.get("name")]
        route_names = [self._format_route(item) for item in apis]

        lines = [
            f"Module summary for {file_path}",
            f"Language: {language}",
            f"Module type: {module_type}",
        ]
        if dependencies:
            lines.append("Dependencies: " + ", ".join(dependencies[:12]))
        if class_names:
            lines.append("Classes: " + ", ".join(class_names[:12]))
        if function_names:
            lines.append("Functions: " + ", ".join(function_names[:12]))
        if route_names:
            lines.append("Routes: " + ", ".join(route_names[:12]))
        if export_names:
            lines.append("Exports: " + ", ".join(export_names[:12]))
        lines.extend(outline[:6])

        structural_summary = "\n".join(lines).strip()
        if function_names or class_names or route_names:
            return structural_summary
        return f"{structural_summary}\n\n{source_text.strip()}".strip()

    def _make_chunks(
        self,
        *,
        file_path: str,
        language: str,
        module_type: str,
        chunk_type: str,
        symbol_name: str | None,
        dependencies: list[str],
        related_symbols: list[str],
        api_routes: list[str],
        body: str,
        start_line: int | None,
        end_line: int | None,
    ) -> list[EmbeddingChunk]:
        normalized_body = body.strip()
        if not normalized_body:
            return []

        metadata_seed = ChunkMetadata(
            chunk_id="",
            file_path=file_path,
            language=language,
            module_type=module_type,
            chunk_type=chunk_type,
            symbol_name=symbol_name,
            dependencies=dependencies[:12],
            source_ref=self._source_ref(file_path, start_line, end_line),
            related_symbols=related_symbols[:12],
            api_routes=api_routes[:12],
            start_line=start_line,
            end_line=end_line,
        )
        body_parts = self._split_body_for_budget(metadata_seed, normalized_body)
        part_count = len(body_parts)
        chunks: list[EmbeddingChunk] = []

        for part_index, part in enumerate(body_parts, start=1):
            chunk_id = self._chunk_id(file_path, chunk_type, symbol_name, part_index)
            metadata = ChunkMetadata(
                chunk_id=chunk_id,
                file_path=file_path,
                language=language,
                module_type=module_type,
                chunk_type=chunk_type,
                symbol_name=symbol_name,
                dependencies=dependencies[:12],
                source_ref=self._source_ref(file_path, start_line, end_line),
                related_symbols=related_symbols[:12],
                api_routes=api_routes[:12],
                start_line=start_line,
                end_line=end_line,
                part_index=part_index,
                part_count=part_count,
            )
            header = self._render_header(metadata)
            chunks.append(EmbeddingChunk(chunk_id=chunk_id, text=f"{header}\n\n{part}", metadata=metadata))

        return chunks

    def _split_body_for_budget(self, metadata: ChunkMetadata, body: str) -> list[str]:
        header = self._render_header(metadata)
        budget = max(self.max_chunk_chars - len(header) - 32, 32)
        if len(header) + 2 + len(body) <= self.max_chunk_chars:
            return [body]

        lines = body.splitlines()
        if not lines:
            return [body[:budget]]

        parts: list[str] = []
        current: list[str] = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1
            if current and current_size + line_size > budget:
                parts.append("\n".join(current).strip())
                overlap = current[-2:] if len(current) > 2 else current[:]
                current = overlap[:]
                current_size = sum(len(item) + 1 for item in current)
            current.append(line)
            current_size += line_size

            while current and current_size > budget:
                oversized = current.pop()
                if current:
                    parts.append("\n".join(current).strip())
                    current = []
                    current_size = 0
                for section in self._split_long_line(oversized, budget):
                    if len(section) > budget:
                        section = section[:budget]
                    parts.append(section.strip())

        if current:
            parts.append("\n".join(current).strip())

        return [part for part in parts if part]

    def _split_long_line(self, value: str, budget: int) -> list[str]:
        if len(value) <= budget:
            return [value]
        return [value[index : index + budget] for index in range(0, len(value), budget)]

    def _render_header(self, metadata: ChunkMetadata) -> str:
        lines = [
            f"File: {metadata.file_path}",
            f"Language: {metadata.language}",
            f"Module type: {metadata.module_type}",
            f"Chunk type: {metadata.chunk_type}",
        ]
        if metadata.symbol_name:
            lines.append(f"Symbol: {metadata.symbol_name}")
        lines.append(f"Source ref: {metadata.source_ref}")
        if metadata.dependencies:
            lines.append("Dependencies: " + ", ".join(metadata.dependencies))
        if metadata.related_symbols:
            lines.append("Related symbols: " + ", ".join(metadata.related_symbols))
        if metadata.api_routes:
            lines.append("Routes: " + ", ".join(metadata.api_routes))
        if metadata.part_count > 1:
            lines.append(f"Chunk part: {metadata.part_index}/{metadata.part_count}")
        return "\n".join(lines)

    def _infer_module_type(
        self,
        file_path: str,
        classes: list[dict[str, Any]],
        apis: list[dict[str, Any]],
    ) -> str:
        normalized = file_path.lower()
        if apis or "route" in normalized or "api" in normalized:
            return "route_module"
        if classes:
            return "class_module"
        return "module"

    def _related_class_names(self, function_name: str, classes: list[dict[str, Any]]) -> list[str]:
        results: list[str] = []
        for class_item in classes:
            methods = self._normalize_string_list(class_item.get("methods"))
            if function_name in methods and class_item.get("name"):
                results.append(str(class_item["name"]))
        return results

    def _extract_location(self, item: dict[str, Any] | None) -> dict[str, int] | None:
        if not item:
            return None
        location = item.get("location")
        if not isinstance(location, dict):
            return None
        start_line = location.get("start_line")
        end_line = location.get("end_line")
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            return None
        return {"start_line": start_line, "end_line": end_line}

    def _slice_source(self, lines: list[str], start_line: int, end_line: int) -> str:
        start_index = max(start_line - 1, 0)
        end_index = max(end_line, start_index)
        return "\n".join(lines[start_index:end_index]).strip()

    def _source_ref(self, file_path: str, start_line: int | None, end_line: int | None) -> str:
        if start_line is None or end_line is None:
            return file_path
        return f"{file_path}:{start_line}-{end_line}"

    def _format_route(self, api_item: dict[str, Any]) -> str:
        method = str(api_item.get("method", "")).strip().upper()
        route = str(api_item.get("route", "")).strip()
        return f"{method} {route}".strip()

    def _chunk_id(
        self,
        file_path: str,
        chunk_type: str,
        symbol_name: str | None,
        part_index: int,
    ) -> str:
        stem = symbol_name or "module"
        normalized = stem.replace(" ", "_").replace("/", "_")
        return f"{file_path}::{chunk_type}::{normalized}::{part_index}"

    def _normalize_items(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        results: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                results.append(item.strip())
        return results
