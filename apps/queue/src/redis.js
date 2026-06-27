import IORedis from "ioredis";

import { config } from "./config.js";

export const createRedisConnection = () =>
  new IORedis(config.redisUrl, {
    maxRetriesPerRequest: null,
    enableReadyCheck: false,
  });
