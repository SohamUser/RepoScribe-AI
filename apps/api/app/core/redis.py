from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()
redis_client: Redis | None = None


async def init_redis_pool() -> Redis:
    global redis_client
    if redis_client is None:
        redis_client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    return redis_client


async def get_redis() -> Redis:
    return await init_redis_pool()


async def check_redis_health() -> bool:
    client = await get_redis()
    return bool(await client.ping())


async def close_redis_pool() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
