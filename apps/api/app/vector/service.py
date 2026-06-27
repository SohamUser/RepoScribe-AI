from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.vector.chunking import CodeChunkingEngine
from app.vector.embedding_service import GeminiEmbeddingService
from app.vector.qdrant_store import QdrantVectorStore
from app.vector.sparse import SparseVectorizer


class VectorService:
    def __init__(
        self,
        *,
        chunking_engine: CodeChunkingEngine | None = None,
        embedding_service: GeminiEmbeddingService | None = None,
        vector_store: QdrantVectorStore | None = None,
        sparse_vectorizer: SparseVectorizer | None = None,
    ) -> None:
        settings = get_settings()
        self.chunking_engine = chunking_engine or CodeChunkingEngine()
        self.embedding_service = embedding_service or GeminiEmbeddingService()
        self.vector_store = vector_store or QdrantVectorStore()
        self.sparse_vectorizer = sparse_vectorizer or SparseVectorizer(
            dimensions=settings.sparse_vector_dimensions
        )

    def build_chunks(
        self,
        repository_root: Path,
        parse_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.chunking_engine.build_chunks(repository_root, parse_result)

    def index_repository(self, repository_name: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        indexed_chunks = 0
        batch_count = 0
        vector_dimensions = 0

        for chunk_batch in self._iter_batches(chunks, self.embedding_service.batch_size):
            embeddings = self.embedding_service.embed_texts([chunk["text"] for chunk in chunk_batch])
            if embeddings and not vector_dimensions:
                vector_dimensions = len(embeddings[0])
                self.vector_store.ensure_collection(repository_name, vector_dimensions)
            if embeddings:
                sparse_embeddings = [self.sparse_vectorizer.encode(chunk["text"]) for chunk in chunk_batch]
                self.vector_store.upsert_points(
                    repository_name,
                    chunk_batch,
                    embeddings,
                    sparse_embeddings,
                )
            indexed_chunks += len(chunk_batch)
            batch_count += 1

        return {
            "repository_name": repository_name,
            "collection_name": self.vector_store.collection_name_for_repository(repository_name),
            "embedding_model": self.embedding_service.model,
            "chunk_count": indexed_chunks,
            "batch_count": batch_count,
            "vector_dimensions": vector_dimensions,
        }

    def index_repository_incremental(
        self,
        *,
        repository_name: str,
        chunks: list[dict[str, Any]],
        changed_file_paths: list[str],
        removed_file_paths: list[str],
    ) -> dict[str, Any]:
        stale_files = sorted(set(changed_file_paths + removed_file_paths))
        if stale_files and self.vector_store.collection_exists(repository_name):
            self.vector_store.delete_points_by_file_paths(repository_name, stale_files)

        index_result = self.index_repository(repository_name, chunks) if chunks else {
            "repository_name": repository_name,
            "collection_name": self.vector_store.collection_name_for_repository(repository_name),
            "embedding_model": self.embedding_service.model,
            "chunk_count": 0,
            "batch_count": 0,
            "vector_dimensions": 0,
        }
        index_result["reindexed_files"] = changed_file_paths
        index_result["removed_files"] = removed_file_paths
        return index_result

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
        dense_embedding = self.embedding_service.embed_texts([query])
        sparse_embedding = self.sparse_vectorizer.encode(query)
        points = self.vector_store.query_points(
            repository=repository_name,
            dense_vector=dense_embedding[0],
            sparse_vector=sparse_embedding,
            limit=limit,
            filters={
                "file_type": file_type,
                "module": module,
                "language": language,
            },
        )
        chunks = [self._point_to_result(point) for point in points]
        return {
            "repository_name": repository_name,
            "query": query,
            "count": len(chunks),
            "chunks": chunks,
        }

    def close(self) -> None:
        self.embedding_service.close()
        self.vector_store.close()

    def _iter_batches(
        self,
        items: list[dict[str, Any]],
        batch_size: int,
    ) -> list[list[dict[str, Any]]]:
        return [
            items[index : index + batch_size]
            for index in range(0, len(items), max(batch_size, 1))
        ]

    def _point_to_result(self, point: dict[str, Any]) -> dict[str, Any]:
        payload = point.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        return {
            "chunk_id": payload.get("chunk_id") or point.get("id"),
            "score": point.get("score"),
            "text": payload.get("text"),
            "repository": payload.get("repository"),
            "file_path": payload.get("file_path"),
            "file_type": payload.get("file_type"),
            "language": payload.get("language"),
            "chunk_type": payload.get("chunk_type"),
            "module_type": payload.get("module_type"),
            "source_ref": payload.get("source_ref"),
            "dependencies": payload.get("dependencies", []),
        }
