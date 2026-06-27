import { Worker } from "bullmq";
import { writeFileSync } from "node:fs";

import { config } from "./config.js";
import { createRedisConnection } from "./redis.js";
import { writeJobStatus } from "./status-store.js";
import { runRepositoryProcessor } from "./python-processor.js";

const workerConnection = createRedisConnection();
const statusRedis = createRedisConnection();

const touchHeartbeat = () => {
  writeFileSync(config.workerHeartbeatFile, new Date().toISOString(), "utf-8");
};

touchHeartbeat();
setInterval(touchHeartbeat, 15000);

const worker = new Worker(
  config.queueName,
  async (job) => {
    await writeJobStatus(statusRedis, job.id, {
      queueName: config.queueName,
      repositoryUrl: job.data.repositoryUrl,
      branch: job.data.branch,
      docTypes: job.data.docTypes ?? [],
      triggerEvent: job.data.triggerEvent ?? null,
      triggerAction: job.data.triggerAction ?? null,
      requestedCommitSha: job.data.requestedCommitSha ?? null,
      status: "processing",
      progress: 0,
      stage: "starting",
      attemptsMade: job.attemptsMade,
      maxAttempts: job.opts.attempts ?? config.jobAttempts,
      startedAt: new Date().toISOString(),
    });

    const result = await runRepositoryProcessor(job.data, async (update) => {
      await job.updateProgress(update.progress);
      await writeJobStatus(statusRedis, job.id, {
        status: "processing",
        progress: update.progress,
        stage: update.stage,
        message: update.message,
        attemptsMade: job.attemptsMade,
        maxAttempts: job.opts.attempts ?? config.jobAttempts,
      });
    });

    return result;
  },
  {
    connection: workerConnection,
    prefix: config.queuePrefix,
    concurrency: config.workerConcurrency,
  },
);

worker.on("completed", async (job, result) => {
  if (!job) {
    return;
  }
  await writeJobStatus(statusRedis, job.id, {
    status: "completed",
    progress: 100,
    stage: "completed",
    completedAt: new Date().toISOString(),
    result,
    attemptsMade: job.attemptsMade,
    maxAttempts: job.opts.attempts ?? config.jobAttempts,
  });
});

worker.on("failed", async (job, error) => {
  if (!job) {
    return;
  }
  const maxAttempts = job.opts.attempts ?? config.jobAttempts;
  const exhausted = job.attemptsMade >= maxAttempts;
  await writeJobStatus(statusRedis, job.id, {
    status: exhausted ? "failed" : "retrying",
    stage: exhausted ? "failed" : "retrying",
    progress: 0,
    error: error.message,
    attemptsMade: job.attemptsMade,
    maxAttempts,
  });
});

worker.on("error", (error) => {
  console.error("[bullmq-worker] worker error", error);
});

console.log(
  `[bullmq-worker] listening on queue=${config.queueName} concurrency=${config.workerConcurrency}`,
);
