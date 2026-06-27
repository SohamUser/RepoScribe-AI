import Fastify from "fastify";

import { config } from "./config.js";
import { createRedisConnection } from "./redis.js";
import { repositoryQueue } from "./queue.js";
import { readJobStatus, writeJobStatus, jobEventsChannel } from "./status-store.js";

const server = Fastify({ logger: true });
const redis = createRedisConnection();

server.get("/health", async () => ({
  status: "ok",
  queueName: config.queueName,
  workerConcurrency: config.workerConcurrency,
}));

server.post("/jobs", async (request, reply) => {
  const payload = request.body ?? {};
  const repositoryUrl = typeof payload.repositoryUrl === "string" ? payload.repositoryUrl.trim() : "";
  const branch = typeof payload.branch === "string" && payload.branch.trim() ? payload.branch.trim() : "main";
  const jobId = typeof payload.jobId === "string" && payload.jobId.trim() ? payload.jobId.trim() : undefined;

  if (!repositoryUrl) {
    return reply.code(400).send({
      error: {
        code: "invalid_payload",
        message: "repositoryUrl is required.",
      },
    });
  }

  const job = await repositoryQueue.add(
    "analyze-repository",
    {
      repositoryUrl,
      branch,
      docTypes: Array.isArray(payload.docTypes) ? payload.docTypes : [],
      triggerEvent: typeof payload.triggerEvent === "string" ? payload.triggerEvent : null,
      triggerAction: typeof payload.triggerAction === "string" ? payload.triggerAction : null,
      requestedCommitSha:
        typeof payload.requestedCommitSha === "string" ? payload.requestedCommitSha : null,
      metadata: typeof payload.metadata === "object" && payload.metadata ? payload.metadata : {},
    },
    {
      jobId,
    },
  );

  const status = await writeJobStatus(redis, job.id, {
    queueName: config.queueName,
    repositoryUrl,
    branch,
    docTypes: Array.isArray(payload.docTypes) ? payload.docTypes : [],
    triggerEvent: typeof payload.triggerEvent === "string" ? payload.triggerEvent : null,
    triggerAction: typeof payload.triggerAction === "string" ? payload.triggerAction : null,
    requestedCommitSha:
      typeof payload.requestedCommitSha === "string" ? payload.requestedCommitSha : null,
    status: "queued",
    progress: 0,
    stage: "queued",
    attemptsMade: 0,
    maxAttempts: job.opts.attempts ?? config.jobAttempts,
    createdAt: new Date().toISOString(),
  });

  return reply.code(202).send(status);
});

server.get("/jobs/:jobId", async (request, reply) => {
  const { jobId } = request.params;
  const status = await readJobStatus(redis, jobId);
  if (!status) {
    return reply.code(404).send({
      error: {
        code: "job_not_found",
        message: `Job ${jobId} was not found.`,
      },
    });
  }

  const job = await repositoryQueue.getJob(jobId);
  const state = job ? await job.getState() : status.status;
  return {
    ...status,
    bullmqState: state,
  };
});

server.get("/jobs/:jobId/events", async (request, reply) => {
  const { jobId } = request.params;
  const subscriber = createRedisConnection();
  const channel = jobEventsChannel(jobId);
  const initial = await readJobStatus(redis, jobId);

  reply.hijack();
  reply.raw.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });

  if (initial) {
    reply.raw.write(`event: status\ndata: ${JSON.stringify(initial)}\n\n`);
  }

  const heartbeat = setInterval(() => {
    reply.raw.write(": keepalive\n\n");
  }, 15000);

  await subscriber.subscribe(channel);
  subscriber.on("message", (_, message) => {
    reply.raw.write(`event: status\ndata: ${message}\n\n`);
  });

  request.raw.on("close", async () => {
    clearInterval(heartbeat);
    await subscriber.unsubscribe(channel);
    subscriber.disconnect();
    reply.raw.end();
  });
});

server.listen({ host: "0.0.0.0", port: config.port }).catch((error) => {
  server.log.error(error);
  process.exit(1);
});
