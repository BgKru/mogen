/** Frontend configuration that mirrors backend limits. */
function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

export const appConfig = {
  maxUploadSizeBytes: positiveInt(import.meta.env.VITE_MAX_UPLOAD_SIZE_MB, 20) * 1024 * 1024,
  maxUploadSizeMb: positiveInt(import.meta.env.VITE_MAX_UPLOAD_SIZE_MB, 20),
  maxSceneImages: positiveInt(import.meta.env.VITE_MAX_SCENE_IMAGES, 100),
  minSceneImages: positiveInt(import.meta.env.VITE_MIN_SCENE_IMAGES, 3),
  taskPollIntervalMs: positiveInt(import.meta.env.VITE_TASK_POLL_INTERVAL, 3000),
} as const;
