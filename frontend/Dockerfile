# syntax=docker/dockerfile:1.7

# Base image is pinned by digest. Update deliberately, then rebuild and test.
ARG NODE_IMAGE=node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85

FROM ${NODE_IMAGE} AS base

WORKDIR /app

ENV CI=true \
    npm_config_fund=false \
    npm_config_audit=false

RUN chown node:node /app

COPY --chown=node:node package.json package-lock.json ./

USER node

RUN npm ci

FROM base AS build

COPY --chown=node:node . .
RUN npm run build

# Development stage serves the application through the Vite dev server and is
# the default build target until the production image is introduced in Phase 4.
FROM base AS development

COPY --chown=node:node . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
