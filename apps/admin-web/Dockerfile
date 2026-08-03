FROM node:22-slim AS build

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH
WORKDIR /app

RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/admin-web/package.json ./apps/admin-web/package.json
COPY apps/customer-web/package.json ./apps/customer-web/package.json
COPY packages/web ./packages/web
RUN pnpm install --frozen-lockfile

COPY apps/admin-web ./apps/admin-web
RUN pnpm --filter geo-production-admin-web build

FROM node:22-slim AS runtime
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
RUN addgroup --system --gid 10001 geo && adduser --system --uid 10001 --ingroup geo geo
COPY --from=build --chown=geo:geo /app/apps/admin-web/.next/standalone ./
COPY --from=build --chown=geo:geo /app/apps/admin-web/.next/static ./apps/admin-web/.next/static
COPY --chown=geo:geo docs/architecture/GEO-runtime-flow-visualization.html ./docs/architecture/GEO-runtime-flow-visualization.html
USER 10001:10001
EXPOSE 3000
CMD ["node", "apps/admin-web/server.js"]
