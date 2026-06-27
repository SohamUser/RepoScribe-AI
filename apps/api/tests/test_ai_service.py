from __future__ import annotations

import json
from typing import Any

import httpx

from app.ai.service import AIService
from app.core.config import Settings


class FakeVectorService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search_repository(
        self,
        *,
        repository_name: str,
        query: str,
        limit: int = 8,
        file_type: str | None = None,
        module: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "repository_name": repository_name,
                "query": query,
                "limit": limit,
                "file_type": file_type,
                "module": module,
                "language": language,
            }
        )
        return {
            "repository_name": repository_name,
            "query": query,
            "count": 2,
            "chunks": [
                {
                    "chunk_id": "src/app.py::function::handler::1",
                    "score": 0.91,
                    "text": "def handler():\n    return {'ok': True}",
                    "file_path": "src/app.py",
                    "language": "Python",
                    "chunk_type": "function",
                    "source_ref": "src/app.py:10-11",
                },
                {
                    "chunk_id": "src/service.py::class::DocService::1",
                    "score": 0.86,
                    "text": "class DocService:\n    pass",
                    "file_path": "src/service.py",
                    "language": "Python",
                    "chunk_type": "class",
                    "source_ref": "src/service.py:3-4",
                },
            ],
        }

    def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True


class StubHTTPClient:
    def __init__(self, response: httpx.Response | None = None, stream_lines: list[str] | None = None) -> None:
        self.response = response
        self.stream_lines = stream_lines or []
        self.posts: list[dict[str, Any]] = []
        self.streams: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        self.posts.append({"url": url, "headers": headers, "json": json})
        assert self.response is not None
        return self.response

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ):
        self.streams.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
            }
        )
        return StreamContext(self.stream_lines)

    def close(self) -> None:
        return None


class StreamContext:
    def __init__(self, lines: list[str]) -> None:
        self.status_code = 200
        self.is_error = False
        self.text = ""
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def iter_lines(self):
        for line in self._lines:
            yield line


def make_response(payload: dict[str, Any]) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test")
    return httpx.Response(status_code=200, json=payload, request=request)


def build_service(
    *,
    response: httpx.Response | None = None,
    stream_lines: list[str] | None = None,
    fake_redis: FakeRedis | None = None,
) -> AIService:
    settings = Settings(
        GEMINI_API_KEY="test-key",
        GEMINI_GENERATION_MODEL="gemini-2.5-flash",
        DOCUMENTATION_RETRIEVAL_LIMIT=4,
        DOCUMENTATION_CONTEXT_CHAR_LIMIT=400,
        CHAT_RETRIEVAL_LIMIT=4,
        CHAT_CONTEXT_CHAR_LIMIT=300,
        CHAT_SNIPPET_CHAR_LIMIT=120,
        CHAT_MAX_SNIPPETS=2,
        CHAT_HISTORY_MAX_MESSAGES=6,
        CHAT_HISTORY_TTL_SECONDS=3600,
        CHAT_HISTORY_CHAR_LIMIT=150,
    )
    service = AIService(
        settings=settings,
        vector_service=FakeVectorService(),
        http_client=StubHTTPClient(response=response, stream_lines=stream_lines),  # type: ignore[arg-type]
    )
    service._get_redis = lambda: fake_redis or FakeRedis()  # type: ignore[attr-defined]
    return service


async def test_ai_service_generates_grounded_documentation() -> None:
    service = build_service(
        response=make_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "# README\n\nOverview grounded in [src/app.py:10-11]."
                                }
                            ]
                        }
                    }
                ]
            }
        )
    )

    result = service.generate_documentation(repository_name="acme/repo", doc_type="readme")

    http_client = service._http_client  # type: ignore[attr-defined]
    vector_service = service.vector_service
    assert result["repository_name"] == "acme/repo"
    assert result["doc_type"] == "readme"
    assert result["references"] == ["src/app.py:10-11", "src/service.py:3-4"]
    assert result["retrieved_chunk_count"] == 2
    prompt = http_client.posts[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "Documentation type: readme" in prompt
    assert "Reference: [src/app.py:10-11]" in prompt
    assert vector_service.calls[0]["repository_name"] == "acme/repo"


async def test_ai_service_streams_markdown_chunks() -> None:
    service = build_service(
        stream_lines=[
            'data: {"candidates":[{"content":{"parts":[{"text":"# README\\n"}]}}]}',
            'data: {"candidates":[{"content":{"parts":[{"text":"\\nSetup from [src/app.py:10-11]."}]}}]}',
        ]
    )

    chunks = list(service.stream_documentation(repository_name="acme/repo", doc_type="onboarding"))

    http_client = service._http_client  # type: ignore[attr-defined]
    assert chunks == ["# README\n", "\nSetup from [src/app.py:10-11]."]
    assert http_client.streams[0]["url"].endswith(":streamGenerateContent?alt=sse")


async def test_ai_service_chat_uses_history_and_returns_snippets() -> None:
    fake_redis = FakeRedis()
    fake_redis.values["repo_chat:acme/repo:session-1"] = json.dumps(
        [
            {"role": "user", "content": "How is routing handled?"},
            {"role": "assistant", "content": "It uses FastAPI style routing."},
        ]
    )
    service = build_service(
        response=make_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "Routing is handled in `handler` [src/app.py:10-11]."
                                }
                            ]
                        }
                    }
                ]
            }
        ),
        fake_redis=fake_redis,
    )

    result = await service.chat_about_repository(
        repository_name="acme/repo",
        question="Where is the request handler defined?",
        session_id="session-1",
        language="Python",
    )

    vector_service = service.vector_service
    assert result["session_id"] == "session-1"
    assert result["references"] == ["src/app.py:10-11", "src/service.py:3-4"]
    assert result["snippets"][0]["source_ref"] == "src/app.py:10-11"
    assert "How is routing handled?" in vector_service.calls[0]["query"]
    assert "Where is the request handler defined?" in vector_service.calls[0]["query"]
    saved_history = json.loads(fake_redis.values["repo_chat:acme/repo:session-1"])
    assert saved_history[-2]["content"] == "Where is the request handler defined?"
    assert saved_history[-1]["content"] == "Routing is handled in `handler` [src/app.py:10-11]."


async def test_ai_service_streams_chat_events_and_persists_history() -> None:
    fake_redis = FakeRedis()
    service = build_service(
        stream_lines=[
            'data: {"candidates":[{"content":{"parts":[{"text":"It lives in "}]}}]}',
            'data: {"candidates":[{"content":{"parts":[{"text":"`handler` [src/app.py:10-11]."}]}}]}',
        ],
        fake_redis=fake_redis,
    )

    events = []
    async for item in service.stream_repository_chat(
        repository_name="acme/repo",
        question="Where is the handler?",
        session_id="session-2",
    ):
        events.append(item)

    assert events[0].startswith("event: meta")
    assert "event: delta" in events[1]
    assert events[-1].startswith("event: done")
    saved_history = json.loads(fake_redis.values["repo_chat:acme/repo:session-2"])
    assert saved_history[-2]["content"] == "Where is the handler?"
    assert saved_history[-1]["content"] == "It lives in `handler` [src/app.py:10-11]."
