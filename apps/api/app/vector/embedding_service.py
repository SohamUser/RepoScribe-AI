from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


class GeminiEmbeddingService:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = self.settings.gemini_embedding_model
        self.api_key = self.settings.gemini_api_key
        self.batch_size = self.settings.gemini_embedding_batch_size
        self.timeout_seconds = self.settings.gemini_embedding_timeout_seconds
        self.max_retries = self.settings.gemini_embedding_max_retries
        self.task_prefix = self.settings.gemini_embedding_task_prefix.strip()
        self._http_client = http_client or httpx.Client(
            base_url=self.settings.gemini_api_base_url.rstrip("/"),
            timeout=self.timeout_seconds,
        )

    def close(self) -> None:
        self._http_client.close()

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for batch in self._iter_batches(list(texts), self.batch_size):
            response_payload = self._post_batch_embed(batch)
            batch_embeddings = self._extract_embeddings(response_payload)
            if len(batch_embeddings) != len(batch):
                raise AppError(
                    message=(
                        f"Gemini embeddings response size mismatch: "
                        f"expected {len(batch)} embeddings but received {len(batch_embeddings)}."
                    ),
                    code="embedding_batch_mismatch",
                )
            embeddings.extend(batch_embeddings)
        return embeddings

    def prepare_chunk_text(self, chunk_text: str) -> str:
        if not self.task_prefix:
            return chunk_text
        return f"{self.task_prefix}\n\n{chunk_text}"

    def _post_batch_embed(self, texts: Sequence[str]) -> dict[str, Any]:
        request_body = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {
                        "parts": [
                            {
                                "text": self.prepare_chunk_text(text),
                            }
                        ]
                    },
                }
                for text in texts
            ]
        }

        for attempt in Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.HTTPError, ServiceUnavailableError)),
            reraise=True,
        ):
            with attempt:
                response = self._http_client.post(
                    f"/v1beta/models/{self.model}:batchEmbedContents",
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.api_key,
                    },
                    json=request_body,
                )
                self._raise_for_status(response, service_name="Gemini embeddings")
                payload = response.json()
                logger.info(
                    "vector.embedding.batch_completed",
                    model=self.model,
                    batch_size=len(texts),
                )
                return payload

        raise ServiceUnavailableError("Gemini embeddings request failed after retries")

    def _extract_embeddings(self, payload: dict[str, Any]) -> list[list[float]]:
        raw_embeddings = payload.get("embeddings")
        if not isinstance(raw_embeddings, list):
            raise AppError(
                message="Gemini embeddings response did not include an embeddings list.",
                code="embedding_response_invalid",
            )

        embeddings: list[list[float]] = []
        for item in raw_embeddings:
            if not isinstance(item, dict):
                continue
            values = item.get("values")
            if values is None and isinstance(item.get("embedding"), dict):
                values = item["embedding"].get("values")
            if not isinstance(values, list):
                raise AppError(
                    message="Gemini embeddings response contained an invalid embedding vector.",
                    code="embedding_vector_invalid",
                )
            embeddings.append([float(value) for value in values])
        return embeddings

    def _raise_for_status(self, response: httpx.Response, service_name: str) -> None:
        if response.status_code in {429, 500, 502, 503, 504}:
            raise ServiceUnavailableError(f"{service_name} is temporarily unavailable")
        if response.is_error:
            raise AppError(
                message=f"{service_name} request failed with status {response.status_code}: {response.text}",
                code="external_service_request_failed",
            )

    def _iter_batches(self, items: list[str], batch_size: int) -> list[list[str]]:
        return [
            items[index : index + batch_size]
            for index in range(0, len(items), max(batch_size, 1))
        ]
