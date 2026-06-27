from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx

from app.core.errors import AppError
from app.core.config import Settings
from app.webhooks.github import GitHubWebhookService


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


class StubAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        self.calls.append({"url": url, "json": json})
        return self.responses.pop(0)

    async def aclose(self) -> None:
        return None


def make_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def make_response(payload: dict[str, Any], status_code: int = 202) -> httpx.Response:
    request = httpx.Request("POST", "http://queue.test/jobs")
    return httpx.Response(status_code=status_code, json=payload, request=request)


def build_service(*, responses: list[httpx.Response], redis: FakeRedis | None = None) -> GitHubWebhookService:
    settings = Settings(
        GITHUB_WEBHOOK_SECRET="test-secret",
        QUEUE_API_URL="http://queue.test",
        GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS=3600,
        GITHUB_WEBHOOK_MAX_RETRIES=2,
    )
    return GitHubWebhookService(
        settings=settings,
        http_client=StubAsyncClient(responses),  # type: ignore[arg-type]
        redis_provider=(lambda: redis or FakeRedis()),
    )


async def test_github_webhook_queues_push_reindex_and_docs() -> None:
    redis = FakeRedis()
    service = build_service(
        responses=[
            make_response(
                {
                    "jobId": "delivery-1",
                    "status": "queued",
                    "repositoryUrl": "https://github.com/acme/repo.git",
                }
            )
        ],
        redis=redis,
    )
    payload = {
        "ref": "refs/heads/main",
        "after": "abc123",
        "repository": {
            "clone_url": "https://github.com/acme/repo.git",
            "full_name": "acme/repo",
        },
        "commits": [
            {
                "modified": ["apps/api/app/api/v1/endpoints/repositories.py", "README.md"],
                "added": ["docker-compose.yml"],
                "removed": [],
            }
        ],
    }
    body = json.dumps(payload).encode("utf-8")

    result = await service.handle_delivery(
        headers={
            "x-github-event": "push",
            "x-github-delivery": "delivery-1",
            "x-hub-signature-256": make_signature("test-secret", body),
        },
        body=body,
    )

    queue_payload = service._http_client.calls[0]["json"]  # type: ignore[attr-defined]
    assert result["status"] == "queued"
    assert queue_payload["branch"] == "main"
    assert queue_payload["requestedCommitSha"] == "abc123"
    assert queue_payload["docTypes"] == ["readme", "architecture", "api", "onboarding"]
    assert json.loads(redis.values["github-webhook-delivery:delivery-1"])["status"] == "queued"


async def test_github_webhook_reuses_duplicate_delivery() -> None:
    redis = FakeRedis()
    redis.values["github-webhook-delivery:delivery-2"] = json.dumps(
        {"status": "queued", "event": "push", "delivery_id": "delivery-2"}
    )
    service = build_service(responses=[], redis=redis)
    body = json.dumps({"repository": {"clone_url": "https://github.com/acme/repo.git"}}).encode("utf-8")

    result = await service.handle_delivery(
        headers={
            "x-github-event": "push",
            "x-github-delivery": "delivery-2",
            "x-hub-signature-256": make_signature("test-secret", body),
        },
        body=body,
    )

    assert result["delivery_id"] == "delivery-2"
    assert result["status"] == "queued"


async def test_github_webhook_queues_pull_request_sync() -> None:
    service = build_service(
        responses=[make_response({"jobId": "delivery-3", "status": "queued"})],
    )
    payload = {
        "action": "synchronize",
        "number": 42,
        "repository": {
            "clone_url": "https://github.com/acme/repo.git",
            "full_name": "acme/repo",
        },
        "pull_request": {
            "head": {
                "ref": "feature-branch",
                "sha": "def456",
                "repo": {
                    "clone_url": "https://github.com/acme/repo.git",
                },
            }
        },
    }
    body = json.dumps(payload).encode("utf-8")

    await service.handle_delivery(
        headers={
            "x-github-event": "pull_request",
            "x-github-delivery": "delivery-3",
            "x-hub-signature-256": make_signature("test-secret", body),
        },
        body=body,
    )

    queue_payload = service._http_client.calls[0]["json"]  # type: ignore[attr-defined]
    assert queue_payload["branch"] == "feature-branch"
    assert queue_payload["docTypes"] == ["architecture", "api"]
    assert queue_payload["triggerAction"] == "synchronize"


async def test_github_webhook_rejects_invalid_signature() -> None:
    service = build_service(responses=[])
    body = json.dumps({"repository": {"clone_url": "https://github.com/acme/repo.git"}}).encode("utf-8")

    try:
        await service.handle_delivery(
            headers={
                "x-github-event": "push",
                "x-github-delivery": "delivery-4",
                "x-hub-signature-256": "sha256=bad",
            },
            body=body,
        )
    except AppError as exc:
        assert exc.code == "invalid_webhook_signature"
        assert exc.status_code == 401
    else:  # pragma: no cover
        raise AssertionError("Expected invalid signature to raise AppError")
