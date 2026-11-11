# syntax=docker/dockerfile:1.7

# Base image is pinned by digest. Update deliberately, then rebuild and test.
ARG NODE_IMAGE=node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85
# Production runtime for the static build and the TLS reverse proxy. Pinned by
# digest: update deliberately, then rebuild and run the deployment checks.
ARG NGINX_IMAGE=nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de

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

# Production stage: the optimized static build served by nginx, which also
# terminates TLS and proxies /api/ and /health/ to the API service
# (08_infrastructure.md Sections 2.4, 3.1 and 8.3). Certificates are mounted
# at runtime and are never copied into the image.
FROM ${NGINX_IMAGE} AS production

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80 443

# `nginx -t` needs the runtime certificates, so configuration syntax is proved
# by the container start and the deployment verification instead of at build.
CMD ["nginx", "-g", "daemon off;"]
