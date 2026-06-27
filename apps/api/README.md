# API

Production-grade FastAPI backend scaffold for repository ingestion, AI workloads, vector retrieval, and repository processing primitives that can be executed by BullMQ workers.

## Structure

```text
app/
  api/
  core/
  services/
  models/
  schemas/
  workers/
  parsers/
  ai/
  vector/
  ingestion/
```

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `GEMINI_API_KEY` before running indexing jobs so the vector pipeline can generate embeddings, and point `QDRANT_URL` at your Qdrant instance.

## Migrations

```bash
alembic upgrade head
```
