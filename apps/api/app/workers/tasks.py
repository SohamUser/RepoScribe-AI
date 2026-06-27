from app.workers.celery_app import celery_app
from app.workers.processor import process_repository_job


@celery_app.task(name="app.workers.tasks.ingest_repository_task")
def ingest_repository_task(repository_url: str, branch: str) -> dict[str, object]:
    return process_repository_job(repository_url=repository_url, branch=branch)
