from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


class QdrantVectorStore:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_retries = self.settings.qdrant_max_retries
        self.wait_for_indexing = self.settings.qdrant_wait_for_indexing
        self._collection_ready: set[str] = set()
        self._http_client = http_client or httpx.Client(
            base_url=self.settings.qdrant_url.rstrip("/"),
            timeout=self.settings.qdrant_timeout_seconds,
        )

    def close(self) -> None:
        self._http_client.close()

    def collection_name_for_repository(self, repository: str) -> str:
        slug = "".join(char.lower() if char.isalnum() else "_" for char in repository).strip("_")
        slug = "_".join(part for part in slug.split("_") if part)
        if not slug:
            slug = "repository"
        return f"{self.settings.qdrant_collection_name}_{slug}"

    def ensure_collection(self, repository: str, vector_size: int) -> str:
        collection_name = self.collection_name_for_repository(repository)
        if collection_name in self._collection_ready:
            return collection_name

        response = self._request("GET", f"/collections/{collection_name}")
        if response.status_code == 404:
            self._create_collection(collection_name, vector_size)
            self._create_filter_indexes(collection_name)
            self._collection_ready.add(collection_name)
            return collection_name

        self._raise_for_status(response, service_name="Qdrant collection lookup")
        configured_size = self._extract_dense_vector_size(response.json())
        if configured_size is not None and configured_size != vector_size:
            raise AppError(
                message=(
                    f"Qdrant collection '{collection_name}' expects dense vector size "
                    f"{configured_size}, but Gemini returned {vector_size}."
                ),
                code="vector_size_mismatch",
            )
        self._collection_ready.add(collection_name)
        return collection_name

    def collection_exists(self, repository: str) -> bool:
        collection_name = self.collection_name_for_repository(repository)
        if collection_name in self._collection_ready:
            return True

        response = self._request("GET", f"/collections/{collection_name}")
        if response.status_code == 404:
            return False

        self._raise_for_status(response, service_name="Qdrant collection lookup")
        self._collection_ready.add(collection_name)
        return True

    def upsert_points(
        self,
        repository: str,
        chunks: Sequence[dict[str, Any]],
        dense_embeddings: Sequence[Sequence[float]],
        sparse_embeddings: Sequence[dict[str, list[float] | list[int]]],
    ) -> str:
        if len(chunks) != len(dense_embeddings) or len(chunks) != len(sparse_embeddings):
            raise AppError(
                message="Chunk and embedding counts must match before Qdrant upsert.",
                code="vector_upsert_mismatch",
            )

        collection_name = self.collection_name_for_repository(repository)
        points = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"{repository}:{chunk['chunk_id']}")),
                "vector": {
                    "dense": [float(value) for value in dense_embedding],
                    "sparse": {
                        "indices": sparse_embedding["indices"],
                        "values": sparse_embedding["values"],
                    },
                },
                "payload": self._build_payload(repository, chunk),
            }
            for chunk, dense_embedding, sparse_embedding in zip(
                chunks,
                dense_embeddings,
                sparse_embeddings,
                strict=True,
            )
        ]

        self._request(
            "PUT",
            f"/collections/{collection_name}/points",
            params={"wait": str(self.wait_for_indexing).lower()},
            json={"points": points},
        )
        logger.info(
            "vector.qdrant.upsert_completed",
            collection_name=collection_name,
            repository=repository,
            point_count=len(points),
        )
        return collection_name

    def query_points(
        self,
        *,
        repository: str,
        dense_vector: Sequence[float],
        sparse_vector: dict[str, list[float] | list[int]] | None,
        limit: int,
        filters: dict[str, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        collection_name = self.collection_name_for_repository(repository)
        request_body: dict[str, Any] = {
            "limit": limit,
            "with_payload": True,
        }
        query_filter = self._build_filter(filters or {})
        if query_filter:
            request_body["filter"] = query_filter

        if sparse_vector and sparse_vector.get("indices"):
            prefetch: list[dict[str, Any]] = [
                {
                    "query": {
                        "indices": sparse_vector["indices"],
                        "values": sparse_vector["values"],
                    },
                    "using": "sparse",
                    "limit": max(limit * 3, limit),
                },
                {
                    "query": [float(value) for value in dense_vector],
                    "using": "dense",
                    "limit": max(limit * 3, limit),
                },
            ]
            if query_filter:
                for item in prefetch:
                    item["filter"] = query_filter
            request_body["prefetch"] = prefetch
            request_body["query"] = {"fusion": "rrf"}
        else:
            request_body["query"] = [float(value) for value in dense_vector]
            request_body["using"] = "dense"

        response = self._request(
            "POST",
            f"/collections/{collection_name}/points/query",
            json=request_body,
        )
        points = response.json().get("result", {}).get("points", [])
        if not isinstance(points, list):
            return []
        return [point for point in points if isinstance(point, dict)]

    def delete_points_by_file_paths(self, repository: str, file_paths: Sequence[str]) -> None:
        if not file_paths:
            return
        collection_name = self.collection_name_for_repository(repository)
        should = [
            {
                "key": "file_path",
                "match": {"value": file_path},
            }
            for file_path in file_paths
        ]
        self._request(
            "POST",
            f"/collections/{collection_name}/points/delete",
            params={"wait": str(self.wait_for_indexing).lower()},
            json={
                "filter": {
                    "should": should,
                }
            },
        )
        logger.info(
            "vector.qdrant.delete_completed",
            collection_name=collection_name,
            repository=repository,
            file_count=len(file_paths),
        )

    def _create_collection(self, collection_name: str, vector_size: int) -> None:
        self._request(
            "PUT",
            f"/collections/{collection_name}",
            json={
                "vectors": {
                    "dense": {
                        "size": vector_size,
                        "distance": self.settings.qdrant_distance_metric,
                    }
                },
                "sparse_vectors": {
                    "sparse": {},
                },
                "on_disk_payload": True,
            },
        )
        logger.info(
            "vector.qdrant.collection_created",
            collection_name=collection_name,
            vector_size=vector_size,
        )

    def _create_filter_indexes(self, collection_name: str) -> None:
        self._create_payload_index(collection_name, "file_path", "keyword")
        self._create_payload_index(collection_name, "file_type", "keyword")
        self._create_payload_index(collection_name, "language", "keyword")
        self._create_payload_index(collection_name, "module_type", "keyword")
        self._create_payload_index(
            collection_name,
            "text",
            {
                "type": "text",
                "tokenizer": "word",
                "min_token_len": 2,
                "max_token_len": 64,
                "lowercase": True,
            },
        )

    def _create_payload_index(self, collection_name: str, field_name: str, field_schema: Any) -> None:
        self._request(
            "PUT",
            f"/collections/{collection_name}/index",
            json={
                "field_name": field_name,
                "field_schema": field_schema,
            },
        )

    def _build_filter(self, filters: dict[str, str | None]) -> dict[str, Any] | None:
        must: list[dict[str, Any]] = []
        for filter_name, payload_key in (
            ("file_type", "file_type"),
            ("module", "module_type"),
            ("language", "language"),
        ):
            value = filters.get(filter_name)
            if value:
                must.append(
                    {
                        "key": payload_key,
                        "match": {"value": value},
                    }
                )
        if not must:
            return None
        return {"must": must}

    def _build_payload(self, repository: str, chunk: dict[str, Any]) -> dict[str, Any]:
        metadata = chunk.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        file_path = metadata.get("file_path")
        return {
            "repository": repository,
            "file_path": file_path,
            "file_type": self._file_type_from_path(file_path),
            "language": metadata.get("language"),
            "chunk_type": metadata.get("chunk_type"),
            "module_type": metadata.get("module_type"),
            "symbol_name": metadata.get("symbol_name"),
            "source_ref": metadata.get("source_ref"),
            "dependencies": metadata.get("dependencies", []),
            "text": chunk.get("text"),
            "chunk_id": chunk.get("chunk_id"),
        }

    def _extract_dense_vector_size(self, payload: dict[str, Any]) -> int | None:
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        config = result.get("config")
        if not isinstance(config, dict):
            return None
        params = config.get("params")
        if not isinstance(params, dict):
            return None
        vectors = params.get("vectors")
        if not isinstance(vectors, dict):
            return None
        dense = vectors.get("dense", vectors)
        if not isinstance(dense, dict):
            return None
        size = dense.get("size")
        return size if isinstance(size, int) else None

    def _file_type_from_path(self, file_path: Any) -> str | None:
        if not isinstance(file_path, str) or "." not in file_path:
            return None
        return file_path.rsplit(".", 1)[-1].lower()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Content-Type": "application/json"}
        if self.settings.qdrant_api_key:
            headers["api-key"] = self.settings.qdrant_api_key

        for attempt in Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.HTTPError, ServiceUnavailableError)),
            reraise=True,
        ):
            with attempt:
                response = self._http_client.request(
                    method=method,
                    url=path,
                    headers=headers,
                    params=params,
                    json=json,
                )
                if method != "GET" or response.status_code != 404:
                    self._raise_for_status(response, service_name="Qdrant")
                return response

        raise ServiceUnavailableError("Qdrant request failed after retries")

    def _raise_for_status(self, response: httpx.Response, service_name: str) -> None:
        if response.status_code in {429, 500, 502, 503, 504}:
            raise ServiceUnavailableError(f"{service_name} is temporarily unavailable")
        if response.is_error:
            raise AppError(
                message=f"{service_name} request failed with status {response.status_code}: {response.text}",
                code="external_service_request_failed",
            )
