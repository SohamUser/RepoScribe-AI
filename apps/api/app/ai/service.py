from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Generator
from typing import Any
from uuid import uuid4

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.vector.service import VectorService

logger = get_logger(__name__)

DOCUMENT_QUERIES = {
    "readme": [
        "repository overview main modules entry points primary workflows",
        "installation setup usage commands environment configuration",
    ],
    "architecture": [
        "system architecture modules services data flow background workers",
        "repository structure integrations storage queues API boundaries",
    ],
    "api": [
        "API routes endpoints request response schemas controllers services",
        "authentication middleware error handling HTTP interfaces",
    ],
    "onboarding": [
        "developer onboarding setup local development testing common workflows",
        "project structure conventions environment variables run commands",
    ],
}

DOCUMENT_SYSTEM_INSTRUCTION = (
    "You generate concise, professional markdown documentation for software repositories. "
    "Use only the supplied retrieval context. Do not invent files, APIs, architecture, or setup steps. "
    "Every substantive section must anchor claims to the provided code references like [path:line-line]. "
    "If context is missing, say so briefly instead of guessing. Prefer short sections, direct language, and accurate code-grounded summaries."
)

CHAT_SYSTEM_INSTRUCTION = (
    "You answer questions about a software repository. "
    "Use only the supplied repository context and recent conversation history. "
    "Do not invent files, behavior, dependencies, or implementation details. "
    "Cite concrete file references like [path:line-line] for claims about code. "
    "When helpful, include short code snippets copied only from the provided context. "
    "Keep answers concise, professional, and directly responsive to the user's question. "
    "If the retrieved context is insufficient, say that briefly instead of guessing."
)


class AIService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        vector_service: VectorService | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_service = vector_service or VectorService()
        self.model = self.settings.gemini_generation_model
        self.timeout_seconds = self.settings.gemini_generation_timeout_seconds
        self.max_retries = self.settings.gemini_generation_max_retries
        self.retrieval_limit = self.settings.documentation_retrieval_limit
        self._owns_vector_service = vector_service is None
        self._get_redis = get_redis
        self._http_client = http_client or httpx.Client(
            base_url=self.settings.gemini_api_base_url.rstrip("/"),
            timeout=self.timeout_seconds,
        )

    def close(self) -> None:
        self._http_client.close()
        if self._owns_vector_service:
            self.vector_service.close()

    def summarize_repository(self, repository_name: str, parse_result: dict[str, object]) -> str:
        stats = parse_result.get("stats", {})
        file_count = stats.get("file_count_estimate", stats.get("file_count", 0))
        return (
            f"Generated AI summary for {repository_name}. "
            f"Estimated indexed files: {file_count}."
        )

    def generate_documentation(
        self,
        *,
        repository_name: str,
        doc_type: str,
    ) -> dict[str, Any]:
        context = self._retrieve_documentation_context(repository_name=repository_name, doc_type=doc_type)
        prompt = self._build_documentation_prompt(
            repository_name=repository_name,
            doc_type=doc_type,
            context=context,
        )
        response = self._post_generate_content(prompt, DOCUMENT_SYSTEM_INSTRUCTION)
        markdown = self._extract_text(response).strip()
        references = self._extract_references(context)
        return {
            "repository_name": repository_name,
            "doc_type": doc_type,
            "markdown": markdown,
            "references": references,
            "retrieved_chunk_count": len(context),
            "model": self.model,
        }

    def stream_documentation(
        self,
        *,
        repository_name: str,
        doc_type: str,
    ) -> Generator[str, None, None]:
        context = self._retrieve_documentation_context(repository_name=repository_name, doc_type=doc_type)
        prompt = self._build_documentation_prompt(
            repository_name=repository_name,
            doc_type=doc_type,
            context=context,
        )
        request_body = self._build_generation_request(prompt, DOCUMENT_SYSTEM_INSTRUCTION)
        for line in self._stream_generate_content(request_body):
            yield line

    async def chat_about_repository(
        self,
        *,
        repository_name: str,
        question: str,
        session_id: str | None = None,
        file_type: str | None = None,
        module: str | None = None,
        language: str | None = None,
    ) -> dict[str, Any]:
        session_id = session_id or str(uuid4())
        history = await self._load_chat_history(repository_name=repository_name, session_id=session_id)
        retrieval_query = self._build_chat_retrieval_query(history=history, question=question)
        retrieval = self.vector_service.search_repository(
            repository_name=repository_name,
            query=retrieval_query,
            limit=self.settings.chat_retrieval_limit,
            file_type=file_type,
            module=module,
            language=language,
        )
        context = self._normalize_chunks(retrieval.get("chunks", []))
        prompt = self._build_chat_prompt(
            repository_name=repository_name,
            question=question,
            history=history,
            context=context,
        )
        response = self._post_generate_content(prompt, CHAT_SYSTEM_INSTRUCTION)
        answer = self._extract_text(response).strip()
        snippets = self._build_chat_snippets(context)
        references = self._extract_references(context)
        await self._append_chat_history(
            repository_name=repository_name,
            session_id=session_id,
            question=question,
            answer=answer,
        )
        return {
            "repository_name": repository_name,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "references": references,
            "snippets": snippets,
            "retrieved_chunk_count": len(context),
            "model": self.model,
        }

    async def stream_repository_chat(
        self,
        *,
        repository_name: str,
        question: str,
        session_id: str | None = None,
        file_type: str | None = None,
        module: str | None = None,
        language: str | None = None,
    ) -> AsyncGenerator[str, None]:
        session_id = session_id or str(uuid4())
        history = await self._load_chat_history(repository_name=repository_name, session_id=session_id)
        retrieval_query = self._build_chat_retrieval_query(history=history, question=question)
        retrieval = self.vector_service.search_repository(
            repository_name=repository_name,
            query=retrieval_query,
            limit=self.settings.chat_retrieval_limit,
            file_type=file_type,
            module=module,
            language=language,
        )
        context = self._normalize_chunks(retrieval.get("chunks", []))
        snippets = self._build_chat_snippets(context)
        references = self._extract_references(context)
        prompt = self._build_chat_prompt(
            repository_name=repository_name,
            question=question,
            history=history,
            context=context,
        )
        request_body = self._build_generation_request(prompt, CHAT_SYSTEM_INSTRUCTION)

        yield self._format_sse_event(
            "meta",
            {
                "repository_name": repository_name,
                "session_id": session_id,
                "question": question,
                "references": references,
                "snippets": snippets,
                "retrieved_chunk_count": len(context),
                "model": self.model,
            },
        )

        answer_parts: list[str] = []
        for part in self._stream_generate_content(request_body):
            answer_parts.append(part)
            yield self._format_sse_event("delta", {"text": part})

        answer = "".join(answer_parts).strip()
        await self._append_chat_history(
            repository_name=repository_name,
            session_id=session_id,
            question=question,
            answer=answer,
        )
        yield self._format_sse_event(
            "done",
            {
                "session_id": session_id,
                "references": references,
                "retrieved_chunk_count": len(context),
            },
        )

    def _retrieve_documentation_context(
        self,
        *,
        repository_name: str,
        doc_type: str,
    ) -> list[dict[str, Any]]:
        queries = DOCUMENT_QUERIES.get(doc_type)
        if not queries:
            raise AppError(message=f"Unsupported documentation type: {doc_type}", code="unsupported_doc_type")

        seen: set[str] = set()
        chunks: list[dict[str, Any]] = []
        for query in queries:
            result = self.vector_service.search_repository(
                repository_name=repository_name,
                query=query,
                limit=self.retrieval_limit,
            )
            for chunk in result.get("chunks", []):
                chunk_id = str(chunk.get("chunk_id", "")).strip()
                if not chunk_id or chunk_id in seen:
                    continue
                seen.add(chunk_id)
                chunks.append(chunk)
        return chunks

    def _build_documentation_prompt(
        self,
        *,
        repository_name: str,
        doc_type: str,
        context: list[dict[str, Any]],
    ) -> str:
        references_block = "\n\n".join(
            self._format_context_chunk(
                ordinal=index + 1,
                chunk=chunk,
                char_limit=self.settings.documentation_context_char_limit,
            )
            for index, chunk in enumerate(context)
        )
        if not references_block:
            references_block = "No code context was retrieved."

        return (
            f"Repository: {repository_name}\n"
            f"Documentation type: {doc_type}\n\n"
            "Write markdown only.\n"
            "Requirements:\n"
            "- Keep the document concise and professional.\n"
            "- Include code references in brackets using the provided source refs.\n"
            "- Do not claim anything that is not directly supported by retrieved chunks.\n"
            "- If important information is missing, state that briefly.\n"
            "- Tailor the output to the requested documentation type.\n\n"
            "Retrieved code context:\n"
            f"{references_block}\n"
        )

    def _build_chat_prompt(
        self,
        *,
        repository_name: str,
        question: str,
        history: list[dict[str, str]],
        context: list[dict[str, Any]],
    ) -> str:
        history_block = self._format_chat_history(history)
        context_block = "\n\n".join(
            self._format_context_chunk(
                ordinal=index + 1,
                chunk=chunk,
                char_limit=self.settings.chat_context_char_limit,
            )
            for index, chunk in enumerate(context)
        )
        if not history_block:
            history_block = "No prior conversation."
        if not context_block:
            context_block = "No code context was retrieved."

        return (
            f"Repository: {repository_name}\n"
            f"User question: {question}\n\n"
            "Answer in markdown.\n"
            "Requirements:\n"
            "- Answer the question directly.\n"
            "- Ground claims in the retrieved code context.\n"
            "- Include file references like [path:line-line].\n"
            "- Include short code snippets only when they help answer the question.\n"
            "- If context is insufficient, say that briefly.\n\n"
            "Recent conversation:\n"
            f"{history_block}\n\n"
            "Retrieved repository context:\n"
            f"{context_block}\n"
        )

    def _build_generation_request(self, prompt: str, system_instruction: str) -> dict[str, Any]:
        return {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.8,
                "maxOutputTokens": self.settings.gemini_generation_max_output_tokens,
                "responseMimeType": "text/plain",
            },
        }

    def _post_generate_content(self, prompt: str, system_instruction: str) -> dict[str, Any]:
        request_body = self._build_generation_request(prompt, system_instruction)
        for attempt in Retrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.HTTPError, ServiceUnavailableError)),
            reraise=True,
        ):
            with attempt:
                response = self._http_client.post(
                    f"/v1beta/models/{self.model}:generateContent",
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": self.settings.gemini_api_key,
                    },
                    json=request_body,
                )
                self._raise_for_status(response, service_name="Gemini generation")
                return response.json()
        raise ServiceUnavailableError("Gemini content generation failed after retries")

    def _stream_generate_content(self, request_body: dict[str, Any]) -> Generator[str, None, None]:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.settings.gemini_api_key,
        }
        with self._http_client.stream(
            "POST",
            f"/v1beta/models/{self.model}:streamGenerateContent?alt=sse",
            headers=headers,
            json=request_body,
        ) as response:
            self._raise_for_status(response, service_name="Gemini streaming generation")
            for line in response.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                text = self._extract_text(payload)
                if text:
                    yield text

    def _extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        if not isinstance(candidates, list):
            return ""
        texts: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content", {})
            if not isinstance(content, dict):
                continue
            parts = content.get("parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
        return "".join(texts)

    def _format_context_chunk(
        self,
        *,
        ordinal: int,
        chunk: dict[str, Any],
        char_limit: int,
    ) -> str:
        file_path = chunk.get("file_path") or "unknown"
        source_ref = chunk.get("source_ref") or file_path
        language = chunk.get("language") or "unknown"
        chunk_type = chunk.get("chunk_type") or "unknown"
        score = chunk.get("score")
        text = str(chunk.get("text") or "").strip()
        if len(text) > char_limit:
            text = text[:char_limit].rstrip() + "\n..."
        return (
            f"[Chunk {ordinal}]\n"
            f"Reference: [{source_ref}]\n"
            f"File: {file_path}\n"
            f"Language: {language}\n"
            f"Chunk type: {chunk_type}\n"
            f"Score: {score}\n"
            f"Content:\n{text}"
        )

    def _extract_references(self, context: list[dict[str, Any]]) -> list[str]:
        references: list[str] = []
        for chunk in context:
            source_ref = chunk.get("source_ref")
            if isinstance(source_ref, str) and source_ref not in references:
                references.append(source_ref)
        return references

    def _build_chat_snippets(self, context: list[dict[str, Any]]) -> list[dict[str, str]]:
        snippets: list[dict[str, str]] = []
        for chunk in context[: self.settings.chat_max_snippets]:
            source_ref = str(chunk.get("source_ref") or chunk.get("file_path") or "unknown")
            file_path = str(chunk.get("file_path") or "unknown")
            language = str(chunk.get("language") or "text").lower()
            code = str(chunk.get("text") or "").strip()
            if len(code) > self.settings.chat_snippet_char_limit:
                code = code[: self.settings.chat_snippet_char_limit].rstrip() + "\n..."
            snippets.append(
                {
                    "source_ref": source_ref,
                    "file_path": file_path,
                    "language": language,
                    "code": code,
                }
            )
        return snippets

    def _format_chat_history(self, history: list[dict[str, str]]) -> str:
        if not history:
            return ""
        formatted: list[str] = []
        recent_history = history[-self.settings.chat_history_max_messages :]
        for message in recent_history:
            role = message.get("role", "user")
            content = message.get("content", "").strip()
            if len(content) > self.settings.chat_history_char_limit:
                content = content[: self.settings.chat_history_char_limit].rstrip() + "..."
            formatted.append(f"{role.title()}: {content}")
        return "\n".join(formatted)

    def _build_chat_retrieval_query(self, *, history: list[dict[str, str]], question: str) -> str:
        prior_questions = [
            message.get("content", "").strip()
            for message in history
            if message.get("role") == "user" and message.get("content")
        ]
        recent_questions = prior_questions[-2:]
        parts = recent_questions + [question.strip()]
        return "\n".join(part for part in parts if part)

    def _normalize_chunks(self, chunks: Any) -> list[dict[str, Any]]:
        if not isinstance(chunks, list):
            return []
        return [chunk for chunk in chunks if isinstance(chunk, dict)]

    async def _load_chat_history(
        self,
        *,
        repository_name: str,
        session_id: str,
    ) -> list[dict[str, str]]:
        client = await self._get_redis()
        raw_value = await client.get(self._chat_key(repository_name, session_id))
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        history: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if isinstance(role, str) and isinstance(content, str):
                history.append({"role": role, "content": content})
        return history

    async def _append_chat_history(
        self,
        *,
        repository_name: str,
        session_id: str,
        question: str,
        answer: str,
    ) -> None:
        history = await self._load_chat_history(repository_name=repository_name, session_id=session_id)
        history.extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )
        history = history[-self.settings.chat_history_max_messages :]
        client = await self._get_redis()
        await client.set(
            self._chat_key(repository_name, session_id),
            json.dumps(history),
            ex=self.settings.chat_history_ttl_seconds,
        )

    def _chat_key(self, repository_name: str, session_id: str) -> str:
        return f"repo_chat:{repository_name}:{session_id}"

    def _format_sse_event(self, event_name: str, payload: dict[str, Any]) -> str:
        return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"

    def _raise_for_status(self, response: httpx.Response, service_name: str) -> None:
        if response.status_code in {429, 500, 502, 503, 504}:
            raise ServiceUnavailableError(f"{service_name} is temporarily unavailable")
        if response.is_error:
            raise AppError(
                message=f"{service_name} request failed with status {response.status_code}: {response.text}",
                code="external_service_request_failed",
            )
