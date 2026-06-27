import { spawn } from "node:child_process";

import { config } from "./config.js";

export function runRepositoryProcessor(jobData, onProgress) {
  const docTypeArgs = Array.isArray(jobData.docTypes)
    ? jobData.docTypes.flatMap((docType) => ["--doc-type", docType])
    : [];
  const triggerEventArgs = jobData.triggerEvent ? ["--trigger-event", jobData.triggerEvent] : [];
  const triggerActionArgs = jobData.triggerAction ? ["--trigger-action", jobData.triggerAction] : [];
  const commitArgs = jobData.requestedCommitSha
    ? ["--requested-commit-sha", jobData.requestedCommitSha]
    : [];

  return new Promise((resolve, reject) => {
    const child = spawn(
      config.pythonCommand,
      [
        "-m",
        config.pythonModule,
        "--repository-url",
        jobData.repositoryUrl,
        "--branch",
        jobData.branch,
        ...docTypeArgs,
        ...triggerEventArgs,
        ...triggerActionArgs,
        ...commitArgs,
      ],
      {
        cwd: config.pythonCwd,
        env: process.env,
      },
    );

    let stdoutBuffer = "";
    let stderrBuffer = "";
    let finalResult = null;

    const consumeLine = async (line) => {
      if (!line.trim()) {
        return;
      }
      let payload;
      try {
        payload = JSON.parse(line);
      } catch {
        return;
      }
      if (payload.type === "progress") {
        await onProgress({
          progress: payload.progress ?? 0,
          stage: payload.stage ?? "processing",
          message: payload.message ?? "Processing repository",
        });
      }
      if (payload.type === "result") {
        finalResult = payload.result ?? null;
      }
      if (payload.type === "error") {
        stderrBuffer = payload.message ? `${stderrBuffer}\n${payload.message}`.trim() : stderrBuffer;
      }
    };

    child.stdout.on("data", (chunk) => {
      stdoutBuffer += chunk.toString();
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) {
        void consumeLine(line);
      }
    });

    child.stderr.on("data", (chunk) => {
      stderrBuffer += chunk.toString();
    });

    child.on("error", (error) => {
      reject(error);
    });

    child.on("close", async (code) => {
      if (stdoutBuffer.trim()) {
        await consumeLine(stdoutBuffer);
      }
      if (code === 0 && finalResult) {
        resolve(finalResult);
        return;
      }
      reject(new Error(stderrBuffer.trim() || `Repository processor exited with code ${code ?? "unknown"}`));
    });
  });
}
