from pathlib import Path

from app.vector.chunking import CodeChunkingEngine


def test_chunking_engine_generates_symbol_and_route_chunks(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    api_file = repository_root / "src" / "api.py"
    api_file.parent.mkdir()
    api_file.write_text(
        "\n".join(
            [
                "from fastapi import APIRouter",
                "from services.user_service import UserService",
                "",
                "router = APIRouter()",
                "",
                "class UserServiceFacade:",
                "    def list_all(self):",
                "        return ['a', 'b']",
                "",
                "def helper(value: str) -> str:",
                "    return value.strip()",
                "",
                "@router.get('/users')",
                "def list_users():",
                "    service = UserServiceFacade()",
                "    return service.list_all()",
            ]
        ),
        encoding="utf-8",
    )

    parse_result = {
        "files": [
            {
                "path": "src/api.py",
                "language": "Python",
                "dependencies": ["fastapi", "services.user_service"],
                "functions": [
                    {
                        "name": "helper",
                        "location": {"start_line": 10, "end_line": 11},
                    },
                    {
                        "name": "list_users",
                        "location": {"start_line": 13, "end_line": 16},
                    },
                ],
                "classes": [
                    {
                        "name": "UserServiceFacade",
                        "methods": ["list_all"],
                        "location": {"start_line": 6, "end_line": 8},
                    }
                ],
                "apis": [
                    {
                        "name": "list_users",
                        "method": "GET",
                        "route": "/users",
                    }
                ],
                "exports": [],
                "llm_outline": ["File: api.py [Python]", "APIs: GET /users"],
            }
        ]
    }

    chunks = CodeChunkingEngine(max_chunk_chars=900).build_chunks(repository_root, parse_result)
    chunk_types = {chunk["metadata"]["chunk_type"] for chunk in chunks}

    assert {"module", "class", "function", "route"} <= chunk_types

    route_chunk = next(chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "route")
    assert route_chunk["metadata"]["file_path"] == "src/api.py"
    assert route_chunk["metadata"]["language"] == "Python"
    assert route_chunk["metadata"]["module_type"] == "route_module"
    assert route_chunk["metadata"]["dependencies"] == ["fastapi", "services.user_service"]
    assert route_chunk["metadata"]["api_routes"] == ["GET /users"]
    assert route_chunk["metadata"]["related_symbols"] == ["list_users"]
    assert route_chunk["metadata"]["source_ref"] == "src/api.py:13-16"
    assert "Dependencies: fastapi, services.user_service" in route_chunk["text"]
    assert "def list_users():" in route_chunk["text"]


def test_chunking_engine_splits_oversized_chunks(tmp_path: Path) -> None:
    repository_root = tmp_path / "repo"
    repository_root.mkdir()
    file_path = repository_root / "src" / "large.py"
    file_path.parent.mkdir()
    large_body = "\n".join(f"    value_{index} = {index}" for index in range(80))
    file_path.write_text(
        f"def oversized():\n{large_body}\n    return value_0\n",
        encoding="utf-8",
    )

    parse_result = {
        "files": [
            {
                "path": "src/large.py",
                "language": "Python",
                "dependencies": ["math"],
                "functions": [
                    {
                        "name": "oversized",
                        "location": {"start_line": 1, "end_line": 82},
                    }
                ],
                "classes": [],
                "apis": [],
                "exports": [],
                "llm_outline": ["File: large.py [Python]"],
            }
        ]
    }

    chunks = CodeChunkingEngine(max_chunk_chars=320).build_chunks(repository_root, parse_result)
    function_chunks = [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "function"]

    assert len(function_chunks) > 1
    assert all(chunk["metadata"]["symbol_name"] == "oversized" for chunk in function_chunks)
    assert all(chunk["metadata"]["source_ref"] == "src/large.py:1-82" for chunk in function_chunks)
    assert [chunk["metadata"]["part_index"] for chunk in function_chunks] == list(
        range(1, len(function_chunks) + 1)
    )
    assert all(chunk["metadata"]["part_count"] == len(function_chunks) for chunk in function_chunks)
    assert all(chunk["metadata"]["file_path"] == "src/large.py" for chunk in function_chunks)
    assert all(len(chunk["text"]) <= 320 for chunk in function_chunks)
