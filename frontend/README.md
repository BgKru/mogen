# Frontend

React + TypeScript application built with Vite. UI language: Russian.

## Current scope (release 1.0.0)

The frontend implements the full MVP workflow:

- Dark application shell with sidebar, topbar, responsive navigation and design
  tokens from the UI/UX specification.
- Registration, login, logout, current-user initialisation and protected routes.
- Project dashboard with statuses, result availability, empty state and deletion.
- Project creation with generation-mode selection and client-side validation.
- Image selection with drag and drop, previews, object-URL cleanup, size and
  format checks, and sequential upload with progress and partial-failure retry.
- Project details with metadata, source images, image deletion/addition.
- Object generation and scene reconstruction start/retry, persisted status and
  real stage polling, stable Russian error messages and the authenticated GLB
  download.
- The unified React Three Fiber viewer at `/projects/:id/result`: authorized GLB
  loading, orbit/zoom/pan, reset/fit, grid, background and fullscreen controls,
  live mesh/vertex/triangle/material/texture metadata, explicit empty,
  processing, failed-regeneration and previous-result states.
- An nginx `production` stage serves the static build, terminates TLS and proxies
  `/api/` and `/health/` (`frontend/nginx/default.conf`).

## Stack

React 19.3.1, TypeScript 5.9.3, Vite 8.3.6, Tailwind CSS 4, React Router 8,
TanStack Query 5, Axios, React Hook Form, Zod, React Three Fiber 9.8.2, Drei
10.7.9, Three.js 0.187.0, Vitest and React Testing Library.

## Scripts

| Command                 | Purpose                                        |
| ----------------------- | ---------------------------------------------- |
| `npm run dev`           | Vite dev server on port 5173                   |
| `npm run build`         | Type check, then production build into `dist/` |
| `npm run preview`       | Serve the production build                     |
| `npm run lint`          | ESLint                                         |
| `npm run format`        | Prettier, write mode                           |
| `npm run format:check`  | Prettier, check mode                           |
| `npm run typecheck`     | `tsc --noEmit`                                 |
| `npm run test`          | Vitest in watch mode                           |
| `npm run test:run`      | Vitest once                                    |
| `npm run test:coverage` | Vitest once with the v8 coverage report        |

Inside Docker, run them against the built image so the pinned Node version is used:

```bash
docker compose build frontend
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run test:run   # 148 tests
docker run --rm mogen-frontend:dev npm run build
```

## Environment

| Variable                  | Purpose                                 | Default                                                           |
| ------------------------- | --------------------------------------- | ----------------------------------------------------------------- |
| `VITE_API_BASE_URL`       | API base URL used by the browser        | `/api/v1`                                                         |
| `VITE_API_PROXY_TARGET`   | Dev-server proxy target for `/api`      | `http://localhost:8000` on the host, `http://api:8000` in Compose |
| `VITE_TASK_POLL_INTERVAL` | Status polling interval in milliseconds | `3000`                                                            |
| `VITE_MAX_UPLOAD_SIZE_MB` | Client-side upload size hint            | `20`                                                              |
| `VITE_MIN_SCENE_IMAGES`   | Recommended minimum scene images (hint) | `3`                                                               |
| `VITE_MAX_SCENE_IMAGES`   | Client-side scene image limit           | `100`                                                             |

The upload limits must stay consistent with the backend `MAX_UPLOAD_SIZE_MB`,
`MIN_SCENE_IMAGES` and `MAX_SCENE_IMAGES`. The backend remains authoritative.

`VITE_API_BASE_URL` defaults to a relative path so the browser stays on the same
origin as the dev server and the production nginx proxy. Set it to an absolute
URL only when the API is served from a different origin.

Never put secrets in `VITE_*` variables: they are embedded in the client bundle.

## Routes

| Route                  | Page              | Access        |
| ---------------------- | ----------------- | ------------- |
| `/`                    | Landing           | Public        |
| `/login`               | Login             | Public        |
| `/register`            | Register          | Public        |
| `/dashboard`           | Project dashboard | Authenticated |
| `/projects/new`        | Create project    | Authenticated |
| `/projects/:id`        | Project details   | Authenticated |
| `/projects/:id/result` | 3D viewer         | Authenticated |

The frontend route guard is a usability mechanism; the backend independently
validates every session and project ownership.

## Structure

```text
src/
├── app/
│   ├── layout/        AppLayout (sidebar, topbar, outlet)
│   ├── providers/     Query, Auth, Toast providers
│   ├── router/        AppRouter, ProtectedRoute, routes
│   └── styles/        globals.css, theme.css (design tokens)
├── features/
│   ├── auth/          API, schemas, auth card
│   ├── projects/      API, hooks, project card, preview
│   ├── image-upload/  API, validation, selection hook, dropzone
│   ├── generation/    API, polling, generation panel, status/error labels
│   └── model-viewer/  unified R3F viewer, loader, controls, metadata, cleanup
├── pages/             route-level pages (including the result workspace)
├── shared/
│   ├── api/           Axios client, DTOs, mappers, errors, query keys
│   ├── components/    Button, Input, Alert, badges, dialog, states
│   ├── lib/           formatting, labels, UUID, Zod resolver
│   └── types/         domain types
├── test/              Vitest setup and render helper
└── nginx/             production reverse-proxy configuration
```

## Testing

Vitest and React Testing Library cover formatting, API error mapping, DTO
mappers, the API-client interceptors, image validation, badges, cards, the
dropzone, authentication forms, the dashboard, project creation, project details,
the generation panel, the viewer toolbar/panel/states and a real triangle GLB
fixture parsed with `GLTFLoader`. **148 tests across 24 files** at 1.0.0; line
coverage 71.47%.

The repository Playwright suite lives in [`../e2e/`](../e2e/README.md) and drives
the real browser workflows (including both real generation modes) against a
running stack.

## Notes

- `Dockerfile` stages: `base`, `build`, `development` (Vite dev server, used by
  `compose.yaml`) and `production` (pinned nginx, used by `compose.prod.yaml`).
- The production proxy only publishes 80/443; it redirects HTTP to HTTPS, returns
  404 for `/docs` and `/openapi.json`, and overwrites `X-Forwarded-For`.
- The viewer never modifies the downloaded asset; it disposes geometry,
  materials and textures on result change and unmount.
