# User Guide — mogen 1.0

This guide describes the MVP workflows of the 3D generation application. The
interface is in Russian; the exact on-screen labels are quoted in `backticks`.

**Supported browsers:** current Chromium-based browsers (Chrome, Edge) and
Firefox with WebGL 2 enabled. A desktop or laptop is recommended for the 3D
viewer; the application is responsive but the viewer is not designed for small
phone screens.

---

## 1. Registration and sign-in

1. Open the application URL (for the local production verification:
   `https://localhost`; accept the self-signed certificate warning).
2. On the landing page choose `Регистрация`.
3. Enter an email address, a password of at least 8 characters, and repeat the
   password. Passwords are stored only as Argon2id hashes.
4. After registration you are signed in and land on `Мои проекты`.

To sign in later choose `Вход` and enter the same email and password. The
session lasts 24 hours by default; `Выйти` in the top bar ends it and revokes the
server session. Repeated failed sign-ins are rate limited (HTTP 429) for a short
period; wait a minute before retrying.

There is no password-reset or account-deletion flow in the MVP. Keep the
credentials safe.

---

## 2. Create a project

1. On `Мои проекты` choose `Создать проект`.
2. Enter a name (up to 150 characters) under `Название проекта`.
3. Choose a generation mode:
   - `Генерация объекта` — one photograph of a single object.
   - `Реконструкция сцены` — several overlapping photographs of a place.
4. Add photographs with the drop zone or the file picker. JPEG and PNG are
   accepted; each file must be at most 20 MB and at most 8192 px on its longest
   edge. The browser checks these limits before upload, and the server enforces
   them again.
5. Choose `Создать проект`. The project is created first and the images are
   uploaded sequentially. If an upload fails, the project and the successful
   images are kept; retry from the project page.

All projects are private to their owner. Another account cannot list, open,
download or delete them.

---

## 3. Preparing an object photograph

Object generation uses a single photograph and TripoSR. A good input matters
more than any setting in the application.

- Show **one object** that fills most of the frame.
- Use a plain, contrasting background; the pipeline removes the background
  automatically.
- Avoid heavy occlusion, motion blur and very dark images.
- Keep the object fully inside the frame; the tool crops and pads it.
- A 3/4 view usually reconstructs better than a perfectly flat front view.
- The tool produces an approximate 3D model: the unseen side is inferred and is
  not a measurement of the real object.

---

## 4. Preparing scene photographs

Scene reconstruction uses COLMAP and OpenMVS. The photographs are the only
source of geometry, so capture them carefully.

- Use **at least 3** photographs (the default upper limit is 100). Ten to thirty
  well-spread photographs are usually a good start.
- Keep **60–80 % overlap** between neighbouring photographs.
- Walk around the subject or location and photograph it from several viewpoints.
  A single row of nearly identical frames reconstructs poorly.
- Keep the same lighting and do not mix day and night shots.
- Avoid moving objects (people, cars, water, foliage in wind).
- Avoid blank walls, glass, mirrors and repeated textures; they provide too few
  stable features.
- Do not upload duplicates or near-duplicates; the pipeline rejects identical
  files by SHA-256.
- Do not crop or rotate the photographs; the pipeline handles EXIF orientation.

If reconstruction fails, the error message names the stage and suggests an
action (for example `Фотографии почти не перекрываются`). Improve the capture
and use `Повторить генерацию`.

---

## 5. Start generation and track it

1. Choose `Создать 3D-модель` on the project page.
2. The project status changes to `Ожидание` (`PENDING`) and then `Обработка`
   (`PROCESSING`). Real stages are shown as the worker reports them:
   - object: `Подготовка изображения`, `Создание 3D-модели`, `Экспорт модели`,
     `Проверка результата`;
   - scene: `Поиск характерных точек`, `Сопоставление снимков`,
     `Восстановление положения камер`, `Плотная реконструкция`,
     `Построение сетки`, `Уточнение сетки`, `Создание текстуры`, `Экспорт GLB`
     and the validation steps.
3. Generation runs asynchronously; you may close the page and come back. The
   task state is stored in PostgreSQL, not in the browser.
4. Typical timings on the reference GPU: an object task takes seconds after the
   model is warm; an 11-photograph scene takes several minutes; a 100-photograph
   scene can take about an hour. The UI never shows a fake percentage — only a
   real one when the worker reports it.
5. When the task finishes the status becomes `Завершено` and the panel shows
   `3D-модель готова` or `Сцена готова`.

While a generation task is active, the source images cannot be deleted and a
second generation task cannot be started for the same project.

---

## 6. View the result

Choose `Открыть в 3D` (also available from the project card and the project
header). The result page loads the current GLB through the authenticated API and
displays it in the browser.

Viewer controls:

| Control | Action |
|---|---|
| Drag with the left mouse button | Rotate |
| Mouse wheel / pinch | Zoom |
| Drag with the right mouse button or two fingers | Pan |
| `Сброс` | Reset camera |
| `Вписать` | Fit the model into the view |
| `Сетка` | Toggle the reference grid |
| `Фон` | Toggle the dark/light background |
| `Экран` / `Выйти` | Toggle fullscreen |

The information panel shows the project name, generation type, status, number of
source images, format, file size, creation date and the mesh, vertex, triangle,
material and texture counts. A project without a result explains why; a failed
regeneration keeps the previous successful result visible.

The viewer never modifies the asset. It is for inspection only; use the download
to process the GLB in another application.

---

## 7. Download the GLB

Choose `Скачать GLB` in the generation panel or the result page. The file is
served by the authenticated download endpoint with a safe `.glb` filename. The
download contains exactly the validated binary that the worker stored: object
assets use vertex colours, scene assets embed one texture atlas. The file can be
opened in Blender, Three.js, Windows 3D Viewer and other glTF 2.0 tools.

---

## 8. Failures, retry and data retention

- A failed task shows `Ошибка`, a readable Russian message and a stable error
  code. The previous successful result and its file are preserved.
- Choose `Повторить генерацию` to start a new task. Retrying with the same
  unsuitable inputs usually fails again; fix the input first.
- Deleting a project removes it from the dashboard immediately and queues its
  files for deletion. Image deletion is refused while a generation task uses the
  image.
- Projects, source photographs and results persist across API and worker
  restarts and across a deployment that reuses the named volumes.
- Superseded result files are deleted asynchronously after a successful
  regeneration; the project history row remains.
- Scene workspaces used for diagnostics are pruned after `SCENE_WORKSPACE_RETENTION_HOURS`
  (7 days by default).

---

## 9. Limits and troubleshooting

| Symptom | Meaning / action |
|---|---|
| `413` on upload | File exceeds 20 MB (or the deployment's `MAX_UPLOAD_SIZE_MB`). Resize it. |
| `400` “недопустимые размеры” | Image exceeds `MAX_IMAGE_DIMENSION` (8192 px) or is corrupt. |
| `415` unsupported format | Only JPEG and PNG are accepted; the extension and content must agree. |
| `409` on the second object image | An object project accepts exactly one image. Delete it first. |
| `409` requires at least 3 images | Add more scene photographs. |
| `429` on sign-in/registration | Auth rate limit (10 requests/minute per address). Wait and retry. |
| Scene fails at sparse reconstruction | Photographs do not overlap or have too little detail. Recapture with more overlap and texture. |
| Viewer says the result cannot be loaded | The current result file is missing or invalid; check the API logs and the storage volume. |
| `Не удалось загрузить проект` | The session expired or the project belongs to another user. Sign in again. |

For deployment-level problems (HTTPS, health checks, backups), see
[`deployment.md`](deployment.md). For developer setup and testing, see
[`developer_guide.md`](developer_guide.md).
