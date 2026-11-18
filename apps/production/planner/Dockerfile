# Build context: a clean git archive of the reviewed Planner commit.
# Pass the homelab Planner directory as the named planner-launch context.
# Pass a verified Node 24 LTS Debian image including its sha256 digest.
ARG NODE_IMAGE=node:24.22.3-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54
FROM ${NODE_IMAGE} AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@10.32.1 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/contracts/package.json packages/contracts/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web/src apps/web/src
COPY apps/web/drizzle apps/web/drizzle
COPY apps/web/tsconfig.json apps/web/vite.config.ts apps/web/drizzle.config.ts apps/web/
COPY packages/contracts/src packages/contracts/src
ARG VITE_CLERK_PUBLISHABLE_KEY
RUN test -n "$VITE_CLERK_PUBLISHABLE_KEY" && pnpm build

FROM ${NODE_IMAGE}
WORKDIR /app
# Include the pinned tsx/Drizzle tools and reviewed SQL for migration/operator Jobs.
# No .env, Git metadata, registry login, backend key or production DB credential.
COPY --from=build --chown=1000:1000 /app /app
COPY --from=planner-launch --chown=1000:1000 /launch.mjs /app/launch.mjs
USER 1000:1000
WORKDIR /app/apps/web
ENV NODE_ENV=production PORT=8080 HOST=0.0.0.0
EXPOSE 8080
CMD ["node", "/app/launch.mjs", "serve"]
