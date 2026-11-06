# Frontend

React + TypeScript application built with Vite.

## Phase 3 scope

The frontend now implements the application shell and the Phase 2 backend
integration:

- Dark application shell with sidebar, topbar, responsive navigation and design
  tokens from the UI/UX specification.
- Registration, login, logout, current-user initialisation and protected routes.
- Project dashboard with statuses, result availability, empty state and deletion.
- Project creation with generation-mode selection and client-side validation.
- Image selection with drag and drop, previews, object-URL cleanup, size and
  format checks, and sequential upload with progress and partial-failure retry.
- Project details with metadata, source images, image deletion/addition and a
  clearly disabled generation placeholder (generation arrives in Phase 4).
- Russian UI, matching the primary MVP language.

The 3D viewer, generation initiation and task polling arrive in later phases.

## Stack

React 19, TypeScript, Vite, Tailwind CSS 4, React Router, TanStack Query, Axios,
React Hook Form, Zod, Vitest and React Testing Library.

## Scripts

| Command                | Purpose                                        |
| ---------------------- | ---------------------------------------------- |
| `npm run dev`          | Vite dev server on port 5173                   |
| `npm run build`        | Type check, then production build into `dist/` |
| `npm run preview`      | Serve the production build                     |
| `npm run lint`         | ESLint                                         |
| `npm run format`       | Prettier, write mode                           |
| `npm run format:check` | Prettier, check mode                           |
| `npm run typecheck`    | `tsc --noEmit`                                 |
| `npm run test`         | Vitest in watch mode                           |
| `npm run test:run`     | Vitest once                                    |

Inside Docker, run them against the built image so the pinned Node version is used:

```bash
docker compose build frontend
docker run --rm mogen-frontend:dev npm run lint
docker run --rm mogen-frontend:dev npm run typecheck
docker run --rm mogen-frontend:dev npm run test:run
docker run --rm mogen-frontend:dev npm run build
```

## Environment

| Variable                  | Purpose                                           | Default                                                           |
| ------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| `VITE_API_BASE_URL`       | API base URL used by the browser                  | `/api/v1`                                                         |
| `VITE_API_PROXY_TARGET`   | Dev-server proxy target for `/api`                | `http://localhost:8000` on the host, `http://api:8000` in Compose |
| `VITE_TASK_POLL_INTERVAL` | Status polling interval in milliseconds (Phase 4) | `3000`                                                            |
| `VITE_MAX_UPLOAD_SIZE_MB` | Client-side upload size hint                      | `20`                                                              |
| `VITE_MIN_SCENE_IMAGES`   | Recommended minimum scene images (hint)           | `3`                                                               |
| `VITE_MAX_SCENE_IMAGES`   | Client-side scene image limit                     | `100`                                                             |

The upload limits must stay consistent with the backend `MAX_UPLOAD_SIZE_MB`,
`MIN_SCENE_IMAGES` and `MAX_SCENE_IMAGES`. The backend remains authoritative.

`VITE_API_BASE_URL` defaults to a relative path so the browser stays on the same
origin as the dev server. Set it to an absolute URL only when the API is served
from a different origin.

Never put secrets in `VITE_*` variables: they are embedded in the client bundle.

## Routes

| Route                  | Page              | Access               |
| ---------------------- | ----------------- | -------------------- |
| `/`                    | Landing           | Public               |
| `/login`               | Login             | Public               |
| `/register`            | Register          | Public               |
| `/dashboard`           | Project dashboard | Authenticated        |
| `/projects/new`        | Create project    | Authenticated        |
| `/projects/:id`        | Project details   | Authenticated        |
| `/projects/:id/result` | 3D viewer         | Reserved for Phase 7 |

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
│   └── image-upload/  API, validation, selection hook, dropzone
├── pages/             route-level pages
├── shared/
│   ├── api/           Axios client, DTOs, mappers, errors, query keys
│   ├── components/    Button, Input, Alert, badges, dialog, states
│   ├── lib/           formatting, labels, UUID, Zod resolver
│   └── types/         domain types
└── test/              Vitest setup and render helper
```

## Testing

Vitest and React Testing Library cover formatting, API error mapping, image
validation, badges, cards, the dropzone, authentication forms, the dashboard,
project creation and project details. API calls are mocked at the module or hook
boundary; no test requires a running backend.

Playwright end-to-end tests are deferred to the quality phase rather than added
as a script that cannot run yet.

## Notes

- The production image served by Nginx is introduced in Phase 4; the current
  Dockerfile builds `development` and `build` stages.
- The generation button on the project details page is intentionally disabled
  until the backend exposes the generation endpoint in Phase 4.
