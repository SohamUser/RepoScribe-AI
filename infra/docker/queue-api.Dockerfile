FROM node:22-alpine

WORKDIR /workspace
ENV NODE_ENV=production

RUN addgroup -S appgroup && adduser -S appuser -G appgroup

COPY package.json tsconfig.base.json ./
COPY apps/queue ./apps/queue

RUN npm install

RUN chown -R appuser:appgroup /workspace
USER appuser

EXPOSE 3010

CMD ["npm", "run", "start:api", "--workspace", "@doc-generator/queue"]
