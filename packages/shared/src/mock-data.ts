import type { ChatMessage, DocumentationSection, RepositorySummary } from "./types";

export const repositorySummaries: RepositorySummary[] = [
  {
    id: "repo_1",
    name: "platform-core",
    owner: "acme",
    branch: "main",
    status: "ready",
    lastIndexedAt: "2026-05-17T19:12:00Z",
    filesIndexed: 1248,
    docsGenerated: 86,
    language: "TypeScript",
  },
  {
    id: "repo_2",
    name: "billing-engine",
    owner: "acme",
    branch: "develop",
    status: "indexing",
    lastIndexedAt: "2026-05-17T20:03:00Z",
    filesIndexed: 418,
    docsGenerated: 19,
    language: "Python",
  },
  {
    id: "repo_3",
    name: "dev-portal",
    owner: "acme",
    branch: "main",
    status: "queued",
    lastIndexedAt: "2026-05-17T20:30:00Z",
    filesIndexed: 0,
    docsGenerated: 0,
    language: "Go",
  },
];

export const documentationSections: DocumentationSection[] = [
  { id: "overview", title: "Architecture Overview", description: "System boundaries, entry points, and runtime dependencies.", depth: 0 },
  { id: "ingestion", title: "Repository Ingestion", description: "Clone flow, file selection rules, and queue orchestration.", depth: 0 },
  { id: "parsing", title: "AST Parsing", description: "Language-aware parsing pipeline, symbol extraction, and relationship mapping.", depth: 1 },
  { id: "generation", title: "AI Generation", description: "Prompt assembly, section synthesis, and editorial safeguards.", depth: 0 },
  { id: "search", title: "Vector Search", description: "Embedding retrieval, chunk ranking, and repository chat context assembly.", depth: 0 },
];

export const chatTranscript: ChatMessage[] = [
  {
    id: "msg_1",
    role: "assistant",
    content: "I indexed the repository architecture and can explain services, data flow, and ownership boundaries.",
  },
  {
    id: "msg_2",
    role: "user",
    content: "Which modules are responsible for repository ingestion and background processing?",
  },
  {
    id: "msg_3",
    role: "assistant",
    content: "Repository ingestion is orchestrated by the ingestion use case, while queue dispatch and job execution are handled through Celery-backed task adapters.",
  },
];
