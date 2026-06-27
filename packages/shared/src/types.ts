export type RepositoryStatus = "queued" | "indexing" | "ready" | "failed";

export interface RepositorySummary {
  id: string;
  name: string;
  owner: string;
  branch: string;
  status: RepositoryStatus;
  lastIndexedAt: string;
  filesIndexed: number;
  docsGenerated: number;
  language: string;
}

export interface DocumentationSection {
  id: string;
  title: string;
  description: string;
  depth: number;
}

export interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
}
