FROM node:22-bookworm-slim AS builder

WORKDIR /workspace
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json tsconfig.base.json ./
COPY packages/shared ./packages/shared
COPY apps/web ./apps/web

WORKDIR /workspace/apps/web

RUN npm install --include=optional
RUN npm run build

FROM node:22-bookworm-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1

RUN groupadd --system appgroup && useradd --system --gid appgroup appuser

COPY --from=builder /workspace/apps/web/.next/standalone ./
COPY --from=builder /workspace/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /workspace/apps/web/public ./apps/web/public

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
