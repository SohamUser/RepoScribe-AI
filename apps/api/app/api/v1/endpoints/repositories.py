from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.repository import (
    RepositoryArchitectureRequest,
    RepositoryArchitectureResponse,
    RepositoryCreate,
    RepositoryChatRequest,
    RepositoryChatResponse,
    RepositoryDocumentationRequest,
    RepositoryDocumentationResponse,
    RepositoryIngestRequest,
    RepositoryMetadataResponse,
    RepositoryResponse,
    RepositorySearchRequest,
    RepositorySearchResponse,
)
from app.services.repository_service import RepositoryService

router = APIRouter()


@router.post("", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def create_repository(
    payload: RepositoryCreate,
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryResponse:
    service = RepositoryService(session)
    return await service.create_repository(payload)


@router.post("/ingest", response_model=RepositoryMetadataResponse, status_code=status.HTTP_200_OK)
async def ingest_repository(
    payload: RepositoryIngestRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryMetadataResponse:
    service = RepositoryService(session)
    return await service.ingest_repository(payload)


@router.post("/architecture", response_model=RepositoryArchitectureResponse, status_code=status.HTTP_200_OK)
async def generate_architecture(
    payload: RepositoryArchitectureRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryArchitectureResponse:
    service = RepositoryService(session)
    return await service.generate_architecture(payload)


@router.post("/search", response_model=RepositorySearchResponse, status_code=status.HTTP_200_OK)
async def search_repository(
    payload: RepositorySearchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepositorySearchResponse:
    service = RepositoryService(session)
    return await service.search_repository(payload)


@router.post("/docs", response_model=RepositoryDocumentationResponse, status_code=status.HTTP_200_OK)
async def generate_documentation(
    payload: RepositoryDocumentationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryDocumentationResponse:
    service = RepositoryService(session)
    return await service.generate_documentation(payload)


@router.post("/docs/stream", status_code=status.HTTP_200_OK)
async def stream_documentation(
    payload: RepositoryDocumentationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    service = RepositoryService(session)
    return StreamingResponse(
        service.stream_documentation(payload),
        media_type="text/markdown; charset=utf-8",
    )


@router.post("/chat", response_model=RepositoryChatResponse, status_code=status.HTTP_200_OK)
async def chat_repository(
    payload: RepositoryChatRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RepositoryChatResponse:
    service = RepositoryService(session)
    return await service.chat_repository(payload)


@router.post("/chat/stream", status_code=status.HTTP_200_OK)
async def stream_repository_chat(
    payload: RepositoryChatRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    service = RepositoryService(session)
    return StreamingResponse(
        service.stream_repository_chat(payload),
        media_type="text/event-stream",
    )
