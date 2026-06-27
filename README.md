# AI-Powered GitHub Documentation Generator

Production-oriented monorepo scaffold for generating living documentation from GitHub repositories with AI-assisted ingestion, vector search, and chat.

## Structure

```text
apps/
  api/        FastAPI backend + repository processing runtime
  queue/      BullMQ queue API and distributed workers
  web/        Next.js + shadcn UI frontend
packages/
  shared/     Shared types, navigation, and mock view models
infra/
  docker/     Dockerfiles for local orchestration
```

## Tech Stack

- Frontend: Next.js 16, React 19, shadcn UI, Tailwind CSS 4
- Backend: FastAPI, Pydantic Settings, SQLAlchemy, BullMQ
- Database: PostgreSQL
- Vector DB: Qdrant
- Queue: Redis
- Infra: Docker Compose

## Quick Start

1. Copy `.env.example` to `.env`.
2. Start the full stack:

```bash
docker compose up --build
```

Scale background workers horizontally when needed:

```bash
docker compose up --build --scale worker=3
```

3. Open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- Qdrant: `http://localhost:6333/dashboard`

## Local Development

### Web

```bash
cd apps/web
npm install
npm run dev
```

### API

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

### Queue API

```bash
cd apps/queue
npm install
npm run start:api
```

### Queue Worker

```bash
cd apps/queue
npm install
npm run start:worker
```

## Backend Architecture

The API follows a clean architecture split:

- `domain/`: business entities and repository contracts
- `application/`: orchestration services and use cases
- `infrastructure/`: database, queue, parsers, AI, and vector adapters
- `presentation/`: request and response schemas
- `api/`: HTTP routes and composition

Prepared capabilities:

- Repository ingestion and indexing jobs
- BullMQ-backed repository analysis queue with Redis job state
- AST parsing pipeline hooks
- Gemini embedding generation adapters with batched chunk indexing
- AI documentation generation services
- Qdrant-backed vector search
- Distributed background execution with BullMQ workers

## Frontend Product Areas

- `/dashboard`: ingestion and indexing overview
- `/repositories/upload`: repository onboarding flow
- `/docs/viewer`: generated documentation browser
- `/chat`: repository-aware AI assistant

## Environment Variables

Root `.env` drives Docker Compose and container runtime defaults. App-scoped examples live in:

- `apps/api/.env.example`
- `apps/web/.env.example`

Important indexing settings:

- `GEMINI_API_KEY` for code chunk embeddings
- `GEMINI_EMBEDDING_MODEL` for the embeddings model selection
- `QDRANT_URL` and optional `QDRANT_API_KEY` for vector storage
- `QDRANT_COLLECTION_NAME` for the shared code chunk collection
- `QUEUE_PORT` for the BullMQ queue API
- `BULLMQ_WORKER_CONCURRENCY` for distributed worker throughput

Container runtime notes:

- Compose exposes the requested production services: `frontend`, `api`, `worker`, `postgres`, `redis`, and `qdrant`.
- An internal `queue-api` service is also included because the current BullMQ orchestration layer uses it to enqueue and track repository processing jobs.
- All long-running services include restart policies and health checks.

