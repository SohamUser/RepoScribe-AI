import path from "node:path";
import { fileURLToPath } from "node:url";

const queueRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(queueRoot, "..", "..", "..");

const toNumber = (value, fallback) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const config = {
  port: toNumber(process.env.QUEUE_PORT, 3010),
  redisUrl: process.env.REDIS_URL ?? "redis://localhost:6379/0",
  queueName: process.env.BULLMQ_QUEUE_NAME ?? "repository-analysis",
  queuePrefix: process.env.BULLMQ_PREFIX ?? "doc-generator",
  workerConcurrency: toNumber(process.env.BULLMQ_WORKER_CONCURRENCY, 4),
  workerHeartbeatFile: process.env.BULLMQ_HEARTBEAT_FILE ?? "/tmp/bullmq-worker-heartbeat",
  jobAttempts: toNumber(process.env.BULLMQ_JOB_ATTEMPTS, 3),
  jobBackoffMs: toNumber(process.env.BULLMQ_JOB_BACKOFF_MS, 5000),
  jobTtlSeconds: toNumber(process.env.BULLMQ_JOB_TTL_SECONDS, 86400),
  pythonCommand: process.env.BULLMQ_PYTHON_COMMAND ?? "python",
  pythonCwd: process.env.BULLMQ_PYTHON_CWD ?? path.join(repositoryRoot, "apps", "api"),
  pythonModule: process.env.BULLMQ_PYTHON_MODULE ?? "app.workers.process_repository_cli",
};
