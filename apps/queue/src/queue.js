import { Queue } from "bullmq";

import { config } from "./config.js";
import { createRedisConnection } from "./redis.js";

export const queueConnection = createRedisConnection();

export const repositoryQueue = new Queue(config.queueName, {
  connection: queueConnection,
  prefix: config.queuePrefix,
  defaultJobOptions: {
    attempts: config.jobAttempts,
    removeOnComplete: 1000,
    removeOnFail: 1000,
    backoff: {
      type: "exponential",
      delay: config.jobBackoffMs,
    },
  },
});
