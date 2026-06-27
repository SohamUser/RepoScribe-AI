from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.vector.embedding_service import GeminiEmbeddingService
from app.vector.qdrant_store import QdrantVectorStore
from app.vector.service import VectorService
from app.vector.sparse import SparseVectorizer


class FakeEmbeddingService:
    def __init__(self, batch_size: int = 2) -> None:
        self.batch_size = batch_size
        self.model = "fake-embedding-model"
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(index + 1), float(index + 2), float(index + 3)] for index, _ in enumerate(texts)]

    def close(self) -> None:
        return None


class FakeVectorStore:
    def __init__(self) -> None:
        self.ensure_calls: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self.queries: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.exists = True

    def collection_name_for_repository(self, repository: str) -> str:
        return f"test_code_chunks_{repository.replace('/', '_')}"

    def ensure_collection(self, repository: str, vector_size: int) -> str:
        self.ensure_calls.append({"repository": repository, "vector_size": vector_size})
        return self.collection_name_for_repository(repository)

    def collection_exists(self, repository: str) -> bool:
        return self.exists

    def upsert_points(
        self,
        repository: str,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        sparse_embeddings: list[dict[str, list[float] | list[int]]],
    ) -> str:
        self.upserts.append(
            {
                "repository": repository,
                "chunks": chunks,
                "embeddings": embeddings,
                "sparse_embeddings": sparse_embeddings,
            }
        )
        return self.collection_name_for_repository(repository)

    def delete_points_by_file_paths(self, repository: str, file_paths: list[str]) -> None:
        self.deletes.append({"repository": repository, "file_paths": file_paths})

    def query_points(
        self,
        *,
        repository: str,
        dense_vector: list[float],
        sparse_vector: dict[str, list[float] | list[int]] | None,
        limit: int,
        filters: dict[str, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        self.queries.append(
            {
                "repository": repository,
                "dense_vector": dense_vector,
                "sparse_vector": sparse_vector,
                "limit": limit,
                "filters": filters,
            }
        )
        return [
            {
                "id": "p1",
                "score": 0.91,
                "payload": {
                    "chunk_id": "src/app.py::function::handler::1",
                    "repository": repository,
                    "text": "def handler(): pass",
                    "file_path": "src/app.py",
                    "file_type": "py",
                    "language": "Python",
                    "chunk_type": "function",
                    "module_type": "route_module",
                    "source_ref": "src/app.py:10-12",
                    "dependencies": ["fastapi"],
                },
            }
        ]

    def close(self) -> None:
        return None


class StubHTTPClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return self.responses.pop(0)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json": json,
            }
        )
        return self.responses.pop(0)

    def close(self) -> None:
        return None


def make_response(status_code: int, payload: dict[str, Any]) -> httpx.Response:
    request = httpx.Request("POST", "https://example.test")
    return httpx.Response(status_code=status_code, json=payload, request=request)


def test_vector_service_indexes_chunks_in_batches() -> None:
    embedding_service = FakeEmbeddingService(batch_size=2)
    vector_store = FakeVectorStore()
    service = VectorService(
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    chunks = [
        {
            "chunk_id": "repo::function::one::1",
            "text": "chunk one",
            "metadata": {
                "file_path": "src/one.py",
                "language": "Python",
                "chunk_type": "function",
            },
        },
        {
            "chunk_id": "repo::function::two::1",
            "text": "chunk two",
            "metadata": {
                "file_path": "src/two.py",
                "language": "Python",
                "chunk_type": "function",
            },
        },
        {
            "chunk_id": "repo::module::three::1",
            "text": "chunk three",
            "metadata": {
                "file_path": "src/three.py",
                "language": "Python",
                "chunk_type": "module",
            },
        },
    ]

    result = service.index_repository("acme/repo", chunks)

    assert result["repository_name"] == "acme/repo"
    assert result["collection_name"] == "test_code_chunks_acme_repo"
    assert result["embedding_model"] == "fake-embedding-model"
    assert result["chunk_count"] == 3
    assert result["batch_count"] == 2
    assert result["vector_dimensions"] == 3
    assert embedding_service.calls == [["chunk one", "chunk two"], ["chunk three"]]
    assert vector_store.ensure_calls == [{"repository": "acme/repo", "vector_size": 3}]
    assert len(vector_store.upserts) == 2
    assert vector_store.upserts[0]["repository"] == "acme/repo"
    assert vector_store.upserts[0]["sparse_embeddings"][0]["indices"]


def test_gemini_embedding_service_batches_and_parses_embeddings() -> None:
    settings = Settings(
        GEMINI_API_KEY="test-key",
        GEMINI_EMBEDDING_MODEL="gemini-embedding-2",
        GEMINI_EMBEDDING_BATCH_SIZE=2,
        GEMINI_EMBEDDING_TASK_PREFIX="Represent this code chunk for repository retrieval.",
    )
    http_client = StubHTTPClient(
        [
            make_response(
                200,
                {
                    "embeddings": [
                        {"values": [0.1, 0.2]},
                        {"embedding": {"values": [0.3, 0.4]}},
                    ]
                },
            ),
            make_response(
                200,
                {
                    "embeddings": [
                        {"values": [0.5, 0.6]},
                    ]
                },
            ),
        ]
    )
    service = GeminiEmbeddingService(settings=settings, http_client=http_client)  # type: ignore[arg-type]

    embeddings = service.embed_texts(["alpha", "beta", "gamma"])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    assert len(http_client.calls) == 2
    first_request = http_client.calls[0]["json"]
    assert first_request["requests"][0]["model"] == "models/gemini-embedding-2"
    assert (
        first_request["requests"][0]["content"]["parts"][0]["text"]
        == "Represent this code chunk for repository retrieval.\n\nalpha"
    )


def test_qdrant_store_creates_collection_and_upserts_metadata() -> None:
    settings = Settings(
        QDRANT_URL="http://qdrant.test:6333",
        QDRANT_COLLECTION_NAME="repo_chunks",
        QDRANT_DISTANCE_METRIC="Cosine",
        QDRANT_WAIT_FOR_INDEXING=False,
    )
    http_client = StubHTTPClient(
        [
            make_response(404, {"status": "not_found"}),
            make_response(200, {"result": True}),
            make_response(200, {"result": True}),
            make_response(200, {"result": True}),
            make_response(200, {"result": True}),
            make_response(200, {"result": True}),
            make_response(200, {"result": {"status": "acknowledged"}}),
        ]
    )
    store = QdrantVectorStore(settings=settings, http_client=http_client)  # type: ignore[arg-type]
    chunk = {
        "chunk_id": "src/app.py::function::handler::1",
        "text": "def handler(): pass",
        "metadata": {
            "file_path": "src/app.py",
            "language": "Python",
            "chunk_type": "function",
            "module_type": "route_module",
            "source_ref": "src/app.py:10-12",
            "dependencies": ["fastapi"],
        },
    }

    collection_name = store.ensure_collection("acme/repo", 768)
    store.upsert_points(
        "acme/repo",
        [chunk],
        [[0.1, 0.2, 0.3]],
        [{"indices": [1, 7], "values": [1.0, 2.0]}],
    )

    assert collection_name == "repo_chunks_acme_repo"
    assert len(http_client.calls) == 7
    assert http_client.calls[1]["json"]["vectors"]["dense"]["size"] == 768
    upsert_payload = http_client.calls[6]["json"]["points"][0]["payload"]
    assert upsert_payload["repository"] == "acme/repo"
    assert upsert_payload["file_path"] == "src/app.py"
    assert upsert_payload["file_type"] == "py"
    assert upsert_payload["language"] == "Python"
    assert upsert_payload["chunk_type"] == "function"
    upsert_vector = http_client.calls[6]["json"]["points"][0]["vector"]
    assert upsert_vector["dense"] == [0.1, 0.2, 0.3]
    assert upsert_vector["sparse"]["indices"] == [1, 7]


def test_sparse_vectorizer_produces_keyword_vector() -> None:
    vectorizer = SparseVectorizer(dimensions=256)

    vector = vectorizer.encode("FastAPI router router handler")

    assert vector["indices"]
    assert len(vector["indices"]) == len(vector["values"])


def test_vector_service_searches_repository_with_filters() -> None:
    embedding_service = FakeEmbeddingService(batch_size=2)
    vector_store = FakeVectorStore()
    service = VectorService(
        embedding_service=embedding_service,
        vector_store=vector_store,
    )

    result = service.search_repository(
        repository_name="acme/repo",
        query="fastapi router handler",
        limit=5,
        file_type="py",
        module="route_module",
        language="Python",
    )

    assert result["repository_name"] == "acme/repo"
    assert result["count"] == 1
    assert result["chunks"][0]["file_type"] == "py"
    assert result["chunks"][0]["module_type"] == "route_module"
    assert vector_store.queries[0]["filters"] == {
        "file_type": "py",
        "module": "route_module",
        "language": "Python",
    }


def test_vector_service_incremental_indexing_deletes_stale_files() -> None:
    embedding_service = FakeEmbeddingService(batch_size=2)
    vector_store = FakeVectorStore()
    service = VectorService(
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    chunks = [
        {
            "chunk_id": "repo::function::one::1",
            "text": "chunk one",
            "metadata": {
                "file_path": "src/one.py",
                "language": "Python",
                "chunk_type": "function",
            },
        }
    ]

    result = service.index_repository_incremental(
        repository_name="acme/repo",
        chunks=chunks,
        changed_file_paths=["src/one.py"],
        removed_file_paths=["src/two.py"],
    )

    assert vector_store.deletes == [
        {"repository": "acme/repo", "file_paths": ["src/one.py", "src/two.py"]}
    ]
    assert result["reindexed_files"] == ["src/one.py"]
    assert result["removed_files"] == ["src/two.py"]


def test_vector_service_incremental_indexing_skips_delete_when_collection_missing() -> None:
    embedding_service = FakeEmbeddingService(batch_size=2)
    vector_store = FakeVectorStore()
    vector_store.exists = False
    service = VectorService(
        embedding_service=embedding_service,
        vector_store=vector_store,
    )
    chunks = [
        {
            "chunk_id": "repo::function::one::1",
            "text": "chunk one",
            "metadata": {
                "file_path": "src/one.py",
                "language": "Python",
                "chunk_type": "function",
            },
        }
    ]

    result = service.index_repository_incremental(
        repository_name="acme/repo",
        chunks=chunks,
        changed_file_paths=["src/one.py"],
        removed_file_paths=["src/two.py"],
    )

    assert vector_store.deletes == []
    assert vector_store.ensure_calls == [{"repository": "acme/repo", "vector_size": 3}]
    assert result["reindexed_files"] == ["src/one.py"]
    assert result["removed_files"] == ["src/two.py"]
