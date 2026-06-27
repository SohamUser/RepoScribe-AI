from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.webhooks.github import GitHubWebhookService

router = APIRouter()


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(request: Request) -> dict[str, object]:
    service = GitHubWebhookService()
    try:
        body = await request.body()
        headers = {key.lower(): value for key, value in request.headers.items()}
        return await service.handle_delivery(headers=headers, body=body)
    finally:
        await service.aclose()
