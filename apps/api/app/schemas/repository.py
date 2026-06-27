from pydantic import BaseModel, ConfigDict, Field


class RepositoryCreate(BaseModel):
    provider: str = Field(default="github")
    owner: str
    name: str
    default_branch: str = Field(default="main")
    description: str | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    owner: str
    name: str
    default_branch: str
    description: str | None


class RepositoryIngestRequest(BaseModel):
    repository_url: str
    branch: str = Field(default="main")


class FileTreeNode(BaseModel):
    path: str
    type: str


class RepositoryMetadataResponse(BaseModel):
    repository_url: str
    repository_name: str
    owner: str
    branch: str
    languages: list[str]
    package_managers: list[str]
    frameworks: list[str]
    file_tree: list[FileTreeNode]


class RepositorySearchRequest(BaseModel):
    repository: str
    query: str
    limit: int = Field(default=8, ge=1, le=20)
    file_type: str | None = None
    module: str | None = None
    language: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: str
    score: float | None = None
    text: str | None = None
    repository: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    language: str | None = None
    chunk_type: str | None = None
    module_type: str | None = None
    source_ref: str | None = None
    dependencies: list[str] = Field(default_factory=list)


class RepositorySearchResponse(BaseModel):
    repository_name: str
    query: str
    count: int
    chunks: list[RetrievedChunk]


class RepositoryDocumentationRequest(BaseModel):
    repository: str
    doc_type: str


class RepositoryDocumentationResponse(BaseModel):
    repository_name: str
    doc_type: str
    markdown: str
    references: list[str]
    retrieved_chunk_count: int
    model: str


class ChatSnippet(BaseModel):
    source_ref: str
    file_path: str
    language: str
    code: str


class RepositoryChatRequest(BaseModel):
    repository: str
    question: str
    session_id: str | None = None
    file_type: str | None = None
    module: str | None = None
    language: str | None = None


class RepositoryChatResponse(BaseModel):
    repository_name: str
    session_id: str
    question: str
    answer: str
    references: list[str]
    snippets: list[ChatSnippet]
    retrieved_chunk_count: int
    model: str


class RepositoryArchitectureRequest(BaseModel):
    repository_url: str
    branch: str = Field(default="main")


class RepositoryArchitectureResponse(BaseModel):
    repository_url: str
    repository_name: str
    owner: str
    branch: str
    architecture_type: str
    detected_services: list[str]
    dependency_graph_markdown: str
    service_diagram_markdown: str
    api_flow_diagram_markdown: str
