from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ServiceUnavailableError
from app.core.redis import get_redis

SUPPORTED_PULL_REQUEST_ACTIONS = {"opened", "reopened", "synchronize"}
DOC_TYPE_PRIORITY = ("readme", "architecture", "api", "onboarding")


class GitHubWebhookService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        redis_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client or httpx.AsyncClient(
            base_url=self.settings.queue_api_url.rstrip("/"),
            timeout=20.0,
        )
        self._owns_http_client = http_client is None
        self._get_redis = redis_provider or get_redis

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def handle_delivery(
        self,
        *,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        self._validate_signature(body=body, signature=headers.get("x-hub-signature-256"))
        event_name = headers.get("x-github-event", "")
        delivery_id = headers.get("x-github-delivery", "")
        if not delivery_id:
            raise AppError(message="Missing GitHub delivery header.", status_code=400, code="missing_delivery")

        payload = self._parse_payload(body)

        if event_name == "ping":
            result = {
                "status": "acknowledged",
                "event": "ping",
                "delivery_id": delivery_id,
                "message": "GitHub webhook received.",
            }
            await self._save_delivery(delivery_id, result)
            return result

        previous = await self._load_delivery(delivery_id)
        if previous is not None:
            return previous

        enqueue_payload = self._build_enqueue_payload(
            event_name=event_name,
            delivery_id=delivery_id,
            payload=payload,
        )

        if enqueue_payload is None:
            result = {
                "status": "ignored",
                "event": event_name,
                "delivery_id": delivery_id,
                "message": "Webhook event did not require reindexing.",
            }
            await self._save_delivery(delivery_id, result)
            return result

        queue_result = await self._enqueue_job(enqueue_payload)
        result = {
            "status": "queued",
            "event": event_name,
            "delivery_id": delivery_id,
            "job": queue_result,
        }
        await self._save_delivery(delivery_id, result)
        return result

    def _validate_signature(self, *, body: bytes, signature: str | None) -> None:
        secret = self.settings.github_webhook_secret
        if not secret:
            raise AppError(
                message="GitHub webhook secret is not configured.",
                status_code=503,
                code="webhook_secret_missing",
            )
        if not signature:
            raise AppError(
                message="Missing GitHub signature header.",
                status_code=401,
                code="invalid_webhook_signature",
            )
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AppError(
                message="Invalid GitHub webhook signature.",
                status_code=401,
                code="invalid_webhook_signature",
            )

    def _parse_payload(self, body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppError(message="Invalid webhook payload.", status_code=400, code="invalid_payload") from exc
        if not isinstance(payload, dict):
            raise AppError(message="Invalid webhook payload.", status_code=400, code="invalid_payload")
        return payload

    def _build_enqueue_payload(
        self,
        *,
        event_name: str,
        delivery_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        repository = payload.get("repository", {})
        if not isinstance(repository, dict):
            repository = {}
        repository_url = repository.get("clone_url")
        full_name = repository.get("full_name")

        if event_name == "push":
            ref = str(payload.get("ref", ""))
            branch = ref.removeprefix("refs/heads/") or "main"
            commit_sha = payload.get("after")
            changed_files = self._collect_push_changed_files(payload)
            doc_types = self._affected_doc_types(changed_files)
            return {
                "jobId": delivery_id,
                "repositoryUrl": repository_url,
                "branch": branch,
                "requestedCommitSha": commit_sha,
                "docTypes": doc_types,
                "triggerEvent": event_name,
                "triggerAction": "push",
                "metadata": {
                    "repository": full_name,
                    "changedFiles": changed_files,
                },
            } if isinstance(repository_url, str) and repository_url else None

        if event_name == "pull_request":
            action = str(payload.get("action", ""))
            pull_request = payload.get("pull_request", {})
            if not isinstance(pull_request, dict):
                return None
            if action == "closed" and payload.get("pull_request", {}).get("merged"):
                base = pull_request.get("base", {})
                base_repo = base.get("repo", {}) if isinstance(base, dict) else {}
                if not isinstance(base_repo, dict):
                    base_repo = {}
                branch = str(base.get("ref", "") or repository.get("default_branch", "main"))
                return {
                    "jobId": delivery_id,
                    "repositoryUrl": base_repo.get("clone_url") or repository_url,
                    "branch": branch,
                    "requestedCommitSha": pull_request.get("merge_commit_sha"),
                    "docTypes": ["readme", "architecture", "api", "onboarding"],
                    "triggerEvent": event_name,
                    "triggerAction": action,
                    "metadata": {
                        "repository": full_name,
                        "pullRequestNumber": payload.get("number"),
                    },
                }
            if action not in SUPPORTED_PULL_REQUEST_ACTIONS:
                return None
            head = pull_request.get("head", {})
            if not isinstance(head, dict):
                return None
            head_repo = head.get("repo", {})
            if not isinstance(head_repo, dict):
                head_repo = {}
            return {
                "jobId": delivery_id,
                "repositoryUrl": head_repo.get("clone_url") or repository_url,
                "branch": head.get("ref") or "main",
                "requestedCommitSha": head.get("sha"),
                "docTypes": ["architecture", "api"],
                "triggerEvent": event_name,
                "triggerAction": action,
                "metadata": {
                    "repository": full_name,
                    "pullRequestNumber": payload.get("number"),
                },
            } if (head_repo.get("clone_url") or repository_url) else None

        return None

    def _collect_push_changed_files(self, payload: dict[str, Any]) -> list[str]:
        commits = payload.get("commits", [])
        if not isinstance(commits, list):
            return []
        changed_files: set[str] = set()
        for commit in commits:
            if not isinstance(commit, dict):
                continue
            for key in ("added", "modified", "removed"):
                values = commit.get(key, [])
                if not isinstance(values, list):
                    continue
                for item in values:
                    if isinstance(item, str) and item.strip():
                        changed_files.add(item.strip())
        return sorted(changed_files)

    def _affected_doc_types(self, changed_files: list[str]) -> list[str]:
        if not changed_files:
            return ["architecture"]

        docs: set[str] = set()
        for file_path in changed_files:
            normalized = file_path.lower()
            if normalized.endswith(("readme.md", "readme", ".md")) or "docs/" in normalized:
                docs.add("readme")
                docs.add("onboarding")
            if any(token in normalized for token in ("api", "route", "controller", "schema", "endpoint")):
                docs.add("api")
            if any(token in normalized for token in ("docker", "compose", "infra", "service", "worker", "queue")):
                docs.add("architecture")
            if any(token in normalized for token in ("package.json", "requirements.txt", "pyproject.toml", ".env")):
                docs.add("onboarding")
                docs.add("architecture")
        if not docs:
            docs.add("architecture")
        return [doc_type for doc_type in DOC_TYPE_PRIORITY if doc_type in docs]

    async def _enqueue_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.settings.github_webhook_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type((httpx.HTTPError, ServiceUnavailableError)),
            reraise=True,
        ):
            with attempt:
                response = await self._http_client.post("/jobs", json=payload)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise ServiceUnavailableError("Queue API is temporarily unavailable")
                if response.is_error:
                    raise AppError(
                        message=f"Queue API request failed with status {response.status_code}: {response.text}",
                        status_code=503,
                        code="queue_enqueue_failed",
                    )
                result = response.json()
                return result if isinstance(result, dict) else {"job": result}
        raise ServiceUnavailableError("Queue API request failed after retries")

    async def _load_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        redis = await self._get_redis()
        raw = await redis.get(self._delivery_key(delivery_id))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def _save_delivery(self, delivery_id: str, payload: dict[str, Any]) -> None:
        redis = await self._get_redis()
        await redis.set(
            self._delivery_key(delivery_id),
            json.dumps(payload),
            ex=self.settings.github_webhook_delivery_ttl_seconds,
        )

    def _delivery_key(self, delivery_id: str) -> str:
        return f"github-webhook-delivery:{delivery_id}"
