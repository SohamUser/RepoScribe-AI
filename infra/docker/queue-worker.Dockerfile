FROM node:22-bookworm-slim

WORKDIR /workspace
ENV NODE_ENV=production
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends git python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY package.json tsconfig.base.json ./
COPY apps/queue ./apps/queue
COPY apps/api ./apps/api

RUN npm install && \
    python3 -m venv ${VIRTUAL_ENV} && \
    ${VIRTUAL_ENV}/bin/pip install --no-cache-dir --upgrade pip && \
    ${VIRTUAL_ENV}/bin/pip install --no-cache-dir -r apps/api/requirements.txt

RUN chown -R appuser:appuser /workspace
USER appuser

CMD ["npm", "run", "start:worker", "--workspace", "@doc-generator/queue"]
