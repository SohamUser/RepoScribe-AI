import { config } from "./config.js";

export const jobStatusKey = (jobId) => `${config.queuePrefix}:jobs:${jobId}`;
export const jobEventsChannel = (jobId) => `${config.queuePrefix}:job-events:${jobId}`;

export async function writeJobStatus(redis, jobId, payload) {
  const previous = await readJobStatus(redis, jobId);
  const next = {
    ...previous,
    ...payload,
    jobId,
    updatedAt: new Date().toISOString(),
  };
  await redis.set(jobStatusKey(jobId), JSON.stringify(next), "EX", config.jobTtlSeconds);
  await redis.publish(jobEventsChannel(jobId), JSON.stringify(next));
  return next;
}

export async function readJobStatus(redis, jobId) {
  const raw = await redis.get(jobStatusKey(jobId));
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
