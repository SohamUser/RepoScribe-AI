FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY apps/api ./apps/api

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e ./apps/api

WORKDIR /workspace/apps/api

CMD ["celery", "-A", "app.workers.celery_app.celery_app", "worker", "--loglevel=info"]
