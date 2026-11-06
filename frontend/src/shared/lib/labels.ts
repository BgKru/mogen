import type { ProjectStatus, ProjectType } from "../types/api";

/** Russian UI labels for project statuses (02_ui_ux_specification.md 4.4). */
export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  CREATED: "Создан",
  UPLOADING: "Загрузка",
  PENDING: "Ожидание",
  PROCESSING: "Обработка",
  COMPLETED: "Завершено",
  FAILED: "Ошибка",
};

/** Russian UI labels for generation modes. */
export const PROJECT_TYPE_LABELS: Record<ProjectType, string> = {
  OBJECT: "Генерация объекта",
  SCENE: "Реконструкция сцены",
};

export const PROJECT_TYPE_DESCRIPTIONS: Record<ProjectType, string> = {
  OBJECT: "Создание 3D-модели объекта по одной фотографии.",
  SCENE: "Реконструкция окружения по нескольким фотографиям.",
};

export type StatusTone = "neutral" | "info" | "success" | "error";

/** Visual tone for a project status; labels always accompany the colour. */
export const PROJECT_STATUS_TONES: Record<ProjectStatus, StatusTone> = {
  CREATED: "neutral",
  UPLOADING: "info",
  PENDING: "neutral",
  PROCESSING: "info",
  COMPLETED: "success",
  FAILED: "error",
};

export function isProjectStatus(value: string): value is ProjectStatus {
  return value in PROJECT_STATUS_LABELS;
}
