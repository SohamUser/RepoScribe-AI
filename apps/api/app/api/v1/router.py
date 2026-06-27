from fastapi import APIRouter

from app.api.v1.endpoints import health, repositories, webhooks

router = APIRouter()
router.include_router(health.router, tags=["health"])
router.include_router(repositories.router, prefix="/repositories", tags=["repositories"])
router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
