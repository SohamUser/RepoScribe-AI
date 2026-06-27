from app.architecture.service import ArchitectureVisualizationService
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.service import IngestionService
from app.models.repository import Repository
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
from app.ai.service import AIService
from app.vector.service import VectorService


class RepositoryService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.ingestion_service = IngestionService()
        self.vector_service = VectorService()
        self.ai_service = AIService(vector_service=self.vector_service)
        self.architecture_service = ArchitectureVisualizationService()

    async def create_repository(self, payload: RepositoryCreate) -> RepositoryResponse:
        repository = Repository(
            provider=payload.provider,
            owner=payload.owner,
            name=payload.name,
            default_branch=payload.default_branch,
            description=payload.description,
        )
        self.session.add(repository)
        await self.session.commit()
        await self.session.refresh(repository)
        return RepositoryResponse.model_validate(repository)

    async def ingest_repository(self, payload: RepositoryIngestRequest) -> RepositoryMetadataResponse:
        return await self.ingestion_service.ingest_repository(
            repository_url=str(payload.repository_url),
            branch=payload.branch,
        )

    async def generate_architecture(
        self,
        payload: RepositoryArchitectureRequest,
    ) -> RepositoryArchitectureResponse:
        return await self.architecture_service.generate_repository_architecture(
            repository_url=str(payload.repository_url),
            branch=payload.branch,
        )

    async def search_repository(self, payload: RepositorySearchRequest) -> RepositorySearchResponse:
        result = self.vector_service.search_repository(
            repository_name=payload.repository,
            query=payload.query,
            limit=payload.limit,
            file_type=payload.file_type,
            module=payload.module,
            language=payload.language,
        )
        return RepositorySearchResponse.model_validate(result)

    async def generate_documentation(
        self,
        payload: RepositoryDocumentationRequest,
    ) -> RepositoryDocumentationResponse:
        result = self.ai_service.generate_documentation(
            repository_name=payload.repository,
            doc_type=payload.doc_type,
        )
        return RepositoryDocumentationResponse.model_validate(result)

    def stream_documentation(self, payload: RepositoryDocumentationRequest):
        return self.ai_service.stream_documentation(
            repository_name=payload.repository,
            doc_type=payload.doc_type,
        )

    async def chat_repository(self, payload: RepositoryChatRequest) -> RepositoryChatResponse:
        result = await self.ai_service.chat_about_repository(
            repository_name=payload.repository,
            question=payload.question,
            session_id=payload.session_id,
            file_type=payload.file_type,
            module=payload.module,
            language=payload.language,
        )
        return RepositoryChatResponse.model_validate(result)

    async def stream_repository_chat(self, payload: RepositoryChatRequest):
        async for item in self.ai_service.stream_repository_chat(
            repository_name=payload.repository,
            question=payload.question,
            session_id=payload.session_id,
            file_type=payload.file_type,
            module=payload.module,
            language=payload.language,
        ):
            yield item
