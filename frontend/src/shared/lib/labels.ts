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

/** Real processing stages persisted by the worker
 * (06_object_generation.md 13.3, 07_scene_reconstruction.md 13.3). */
export const GENERATION_STAGE_LABELS: Record<string, string> = {
  IMAGE_PREPARATION: "Подготовка изображения",
  MODEL_GENERATION: "Создание 3D-модели",
  MODEL_EXPORT: "Экспорт модели",
  FEATURE_EXTRACTION: "Поиск характерных точек",
  FEATURE_MATCHING: "Сопоставление снимков",
  SPARSE_RECONSTRUCTION: "Восстановление положения камер",
  RECONSTRUCTION_VALIDATION: "Проверка реконструкции",
  IMAGE_UNDISTORTION: "Исправление дисторсии",
  OPENMVS_IMPORT: "Импорт в OpenMVS",
  DENSE_RECONSTRUCTION: "Плотная реконструкция",
  MESH_GENERATION: "Построение сетки",
  MESH_REFINEMENT: "Уточнение сетки",
  TEXTURING: "Создание текстуры",
  ASSET_EXPORT: "Экспорт GLB",
  RESULT_VALIDATION: "Проверка результата",
};

/** User-facing Russian messages for the stable worker error codes. */
export const GENERATION_ERROR_MESSAGES: Record<string, string> = {
  SOURCE_IMAGE_NOT_FOUND: "Исходная фотография больше недоступна.",
  IMAGE_DECODE_FAILED: "Не удалось прочитать изображение.",
  INVALID_IMAGE_DIMENSIONS: "Недопустимые размеры изображения.",
  BACKGROUND_REMOVAL_FAILED: "Не удалось отделить объект от фона.",
  INVALID_FOREGROUND_MASK: "На фотографии не найден объект.",
  IMAGE_PREPROCESSING_FAILED: "Не удалось подготовить изображение.",
  MODEL_LOAD_FAILED: "Не удалось загрузить модель генерации.",
  MODEL_WEIGHTS_MISSING: "Файлы модели генерации не найдены.",
  MODEL_WEIGHTS_CHECKSUM_MISMATCH: "Файлы модели генерации повреждены.",
  GPU_UNAVAILABLE: "Графический ускоритель недоступен на этом сервере.",
  GPU_OUT_OF_MEMORY: "Недостаточно видеопамяти для генерации.",
  CUDA_EXECUTION_FAILED: "Ошибка вычислений на графическом ускорителе.",
  MODEL_INFERENCE_FAILED: "Не удалось построить 3D-модель.",
  MODEL_TIMEOUT: "Генерация превысила допустимое время.",
  MESH_EXTRACTION_FAILED: "Не удалось извлечь геометрию модели.",
  INVALID_MESH: "Построенная геометрия оказалась некорректной.",
  GLB_EXPORT_FAILED: "Не удалось сохранить модель в формате GLB.",
  GLB_VALIDATION_FAILED: "Сохранённая модель не прошла проверку.",
  STORAGE_WRITE_FAILED: "Не удалось сохранить результат генерации.",
  RESULT_PERSISTENCE_FAILED: "Не удалось зарегистрировать результат генерации.",
  WORKER_UNAVAILABLE: "Обработка генерации недоступна в этой конфигурации.",
  GENERATION_FAILED: "Во время генерации произошла ошибка.",
  INSUFFICIENT_IMAGES: "Для реконструкции нужно не меньше трёх фотографий.",
  DUPLICATE_IMAGES: "В наборе есть одинаковые фотографии — удалите дубликаты.",
  INVALID_SCENE_DATASET: "Набор фотографий не подходит для реконструкции.",
  FEATURE_EXTRACTION_FAILED: "Не удалось найти характерные точки на фотографиях.",
  FEATURE_MATCHING_FAILED: "Не удалось сопоставить фотографии.",
  NO_VALID_MATCHES:
    "Фотографии почти не перекрываются. Сделайте снимки с большим общим полем зрения.",
  SPARSE_RECONSTRUCTION_FAILED:
    "Не удалось восстановить положение камер. Попробуйте снимки с большим перекрытием и разнообразными деталями.",
  INSUFFICIENT_REGISTERED_IMAGES:
    "Не удалось определить камеры для достаточного числа фотографий. Снимки могут не перекрываться или содержать слишком мало деталей.",
  INVALID_CAMERA_PARAMETERS: "Параметры камер получились некорректными.",
  IMAGE_UNDISTORTION_FAILED: "Не удалось подготовить изображения для плотной реконструкции.",
  OPENMVS_IMPORT_FAILED: "Не удалось импортировать реконструкцию в OpenMVS.",
  DENSE_RECONSTRUCTION_FAILED: "Не удалось построить плотное облако точек.",
  INSUFFICIENT_DENSE_POINTS: "Плотное облако точек получилось слишком разреженным.",
  MESH_GENERATION_FAILED: "Не удалось построить сетку сцены.",
  MESH_REFINEMENT_FAILED: "Не удалось уточнить сетку сцены.",
  TEXTURE_GENERATION_FAILED: "Не удалось создать текстуры сцены.",
  INSUFFICIENT_STORAGE: "Недостаточно места для обработки сцены.",
  MEMORY_LIMIT_EXCEEDED: "Обработка превысила доступный объём памяти.",
  TOOL_TIMEOUT: "Этап реконструкции превысил допустимое время.",
  EXTERNAL_TOOL_UNAVAILABLE: "Инструменты реконструкции недоступны на этом сервере.",
};

/**
 * Map a stable error code to a Russian message.
 *
 * The worker's own message is a last resort: it is user-safe by contract, but
 * the stable code is the part that is guaranteed not to leak internals.
 */
export function generationErrorMessage(
  errorCode: string | null | undefined,
  fallback: string | null | undefined,
): string {
  if (errorCode && GENERATION_ERROR_MESSAGES[errorCode]) {
    return GENERATION_ERROR_MESSAGES[errorCode];
  }
  return fallback?.trim() || GENERATION_ERROR_MESSAGES.GENERATION_FAILED;
}
