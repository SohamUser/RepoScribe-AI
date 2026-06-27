from app.core.database import check_database_health
from app.core.redis import check_redis_health
from app.schemas.health import HealthDependency, HealthResponse


class HealthService:
    async def check(self) -> HealthResponse:
        try:
            database_ok = await check_database_health()
        except Exception:
            database_ok = False

        try:
            redis_ok = await check_redis_health()
        except Exception:
            redis_ok = False

        status = "ok" if database_ok and redis_ok else "degraded"
        return HealthResponse(
            status=status,
            version="v1",
            dependencies=[
                HealthDependency(name="database", status="ok" if database_ok else "down"),
                HealthDependency(name="redis", status="ok" if redis_ok else "down"),
            ],
        )
