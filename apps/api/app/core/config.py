from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Doc Generator API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    api_cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000"],
        alias="API_CORS_ORIGINS",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/doc_generator",
        alias="DATABASE_URL",
    )
    database_echo: bool = Field(default=False, alias="DATABASE_ECHO")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection_name: str = Field(default="code_chunks", alias="QDRANT_COLLECTION_NAME")
    qdrant_distance_metric: str = Field(default="Cosine", alias="QDRANT_DISTANCE_METRIC")
    qdrant_timeout_seconds: float = Field(default=30.0, alias="QDRANT_TIMEOUT_SECONDS")
    qdrant_max_retries: int = Field(default=3, alias="QDRANT_MAX_RETRIES")
    qdrant_wait_for_indexing: bool = Field(default=False, alias="QDRANT_WAIT_FOR_INDEXING")
    gemini_api_key: str = Field(default="replace-me", alias="GEMINI_API_KEY")
    gemini_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        alias="GEMINI_API_BASE_URL",
    )
    gemini_embedding_model: str = Field(default="gemini-embedding-2", alias="GEMINI_EMBEDDING_MODEL")
    gemini_embedding_batch_size: int = Field(default=32, alias="GEMINI_EMBEDDING_BATCH_SIZE")
    gemini_embedding_timeout_seconds: float = Field(
        default=60.0,
        alias="GEMINI_EMBEDDING_TIMEOUT_SECONDS",
    )
    gemini_embedding_max_retries: int = Field(default=3, alias="GEMINI_EMBEDDING_MAX_RETRIES")
    gemini_embedding_task_prefix: str = Field(
        default="Represent this code chunk for repository retrieval.",
        alias="GEMINI_EMBEDDING_TASK_PREFIX",
    )
    retrieval_default_limit: int = Field(default=8, alias="RETRIEVAL_DEFAULT_LIMIT")
    retrieval_max_limit: int = Field(default=20, alias="RETRIEVAL_MAX_LIMIT")
    sparse_vector_dimensions: int = Field(default=4096, alias="SPARSE_VECTOR_DIMENSIONS")
    gemini_generation_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_GENERATION_MODEL")
    gemini_generation_timeout_seconds: float = Field(
        default=90.0,
        alias="GEMINI_GENERATION_TIMEOUT_SECONDS",
    )
    gemini_generation_max_retries: int = Field(default=3, alias="GEMINI_GENERATION_MAX_RETRIES")
    gemini_generation_max_output_tokens: int = Field(
        default=4096,
        alias="GEMINI_GENERATION_MAX_OUTPUT_TOKENS",
    )
    documentation_retrieval_limit: int = Field(default=6, alias="DOCUMENTATION_RETRIEVAL_LIMIT")
    documentation_context_char_limit: int = Field(
        default=1800,
        alias="DOCUMENTATION_CONTEXT_CHAR_LIMIT",
    )
    chat_retrieval_limit: int = Field(default=6, alias="CHAT_RETRIEVAL_LIMIT")
    chat_context_char_limit: int = Field(default=1200, alias="CHAT_CONTEXT_CHAR_LIMIT")
    chat_snippet_char_limit: int = Field(default=600, alias="CHAT_SNIPPET_CHAR_LIMIT")
    chat_max_snippets: int = Field(default=3, alias="CHAT_MAX_SNIPPETS")
    chat_history_ttl_seconds: int = Field(default=86400, alias="CHAT_HISTORY_TTL_SECONDS")
    chat_history_max_messages: int = Field(default=8, alias="CHAT_HISTORY_MAX_MESSAGES")
    chat_history_char_limit: int = Field(default=400, alias="CHAT_HISTORY_CHAR_LIMIT")
    queue_api_url: str = Field(default="http://localhost:3010", alias="QUEUE_API_URL")
    github_webhook_delivery_ttl_seconds: int = Field(
        default=172800,
        alias="GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS",
    )
    github_webhook_max_retries: int = Field(default=3, alias="GITHUB_WEBHOOK_MAX_RETRIES")
    openai_api_key: str = Field(default="replace-me", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    ingestion_workdir: str = Field(default="/tmp/doc-generator", alias="INGESTION_WORKDIR")
    github_app_id: str | None = Field(default=None, alias="GITHUB_APP_ID")
    github_app_private_key: str | None = Field(default=None, alias="GITHUB_APP_PRIVATE_KEY")
    github_webhook_secret: str | None = Field(default=None, alias="GITHUB_WEBHOOK_SECRET")

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
