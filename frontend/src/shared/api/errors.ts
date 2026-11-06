/**
 * Normalised API errors.
 *
 * Axios throws different shapes for HTTP errors, network failures and
 * cancellations. The application only deals with `ApiError`, so components can
 * render a stable `status`/`code`/`details` interface.
 */

import { isAxiosError } from "axios";

import type { ApiErrorDetailDto, ApiErrorDto } from "./dto";

export interface ApiErrorDetail {
  field: string | null;
  code: string | null;
  message: string;
}

interface ApiErrorInit {
  status: number;
  code: string;
  message: string;
  details?: ApiErrorDetail[];
  requestId?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetail[];
  readonly requestId: string | null;

  constructor({ status, code, message, details = [], requestId = null }: ApiErrorInit) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

function isErrorDetail(value: unknown): value is ApiErrorDetailDto {
  return (
    typeof value === "object" &&
    value !== null &&
    "message" in value &&
    typeof (value as { message: unknown }).message === "string"
  );
}

function parseDetails(value: unknown): ApiErrorDetail[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter(isErrorDetail).map((detail) => ({
    field: detail.field ?? null,
    code: detail.code ?? null,
    message: detail.message,
  }));
}

/** Convert any thrown value into an `ApiError`. */
export function toApiError(error: unknown): ApiError {
  if (isApiError(error)) {
    return error;
  }

  if (isAxiosError(error)) {
    const status = error.response?.status ?? 0;
    const payload = error.response?.data as ApiErrorDto | undefined;
    const api = payload?.error;
    return new ApiError({
      status,
      code: api?.code ?? (status ? `HTTP_${status}` : "NETWORK_ERROR"),
      message: api?.message ?? (status ? "Запрос не выполнен." : ""),
      details: parseDetails(api?.details),
      requestId: api?.request_id ?? null,
    });
  }

  if (error instanceof Error) {
    return new ApiError({
      status: 0,
      code: "UNKNOWN_ERROR",
      message: error.message,
      requestId: null,
    });
  }

  return new ApiError({
    status: 0,
    code: "UNKNOWN_ERROR",
    message: "Неизвестная ошибка.",
    requestId: null,
  });
}

const CODE_MESSAGES: Record<string, string> = {
  UNAUTHORIZED: "Требуется вход в систему.",
  SESSION_EXPIRED: "Сессия истекла. Войдите снова.",
  INVALID_CREDENTIALS: "Неверный email или пароль.",
  EMAIL_ALREADY_REGISTERED: "Аккаунт с таким email уже существует.",
  CSRF_VALIDATION_FAILED: "Не удалось подтвердить безопасность запроса. Обновите страницу.",
  PROJECT_NOT_FOUND: "Проект не найден.",
  PROJECT_NAME_INVALID: "Проверьте название проекта.",
  IMAGE_TOO_LARGE: "Файл слишком большой.",
  IMAGE_DIMENSIONS_EXCEEDED: "Размеры изображения превышают допустимые.",
  IMAGE_COUNT_EXCEEDED: "Достигнут лимит изображений для этого проекта.",
  IMAGE_NOT_FOUND: "Изображение не найдено.",
  INVALID_IMAGE_FORMAT: "Формат файла не поддерживается. Используйте JPEG или PNG.",
  INVALID_IMAGE_CONTENT: "Файл не является корректным изображением.",
  INVALID_PROJECT_STATE: "Текущее состояние проекта не позволяет выполнить действие.",
  STORAGE_UNAVAILABLE: "Хранилище временно недоступно. Попробуйте позже.",
  VALIDATION_ERROR: "Проверьте правильность заполнения полей.",
  INTERNAL_SERVER_ERROR: "Внутренняя ошибка сервера. Попробуйте позже.",
  NETWORK_ERROR: "Нет соединения с сервером. Проверьте подключение и повторите попытку.",
  UNKNOWN_ERROR: "Не удалось выполнить запрос. Попробуйте позже.",
};

/** Translate an error into a user-facing Russian message. */
export function userMessageFor(error: unknown): string {
  const apiError = toApiError(error);

  if (apiError.code && CODE_MESSAGES[apiError.code]) {
    return CODE_MESSAGES[apiError.code];
  }
  if (apiError.status === 0) {
    return CODE_MESSAGES.NETWORK_ERROR;
  }
  if (apiError.status === 401) {
    return CODE_MESSAGES.UNAUTHORIZED;
  }
  if (apiError.status === 403) {
    return "Действие запрещено.";
  }
  if (apiError.status === 404) {
    return "Ресурс не найден.";
  }
  if (apiError.status === 409) {
    return "Операция конфликтует с текущим состоянием проекта.";
  }
  if (apiError.status === 413) {
    return "Файл слишком большой.";
  }
  if (apiError.status === 415) {
    return "Формат файла не поддерживается.";
  }
  if (apiError.status === 422) {
    return CODE_MESSAGES.VALIDATION_ERROR;
  }
  if (apiError.status === 429) {
    return "Слишком много запросов. Попробуйте немного позже.";
  }
  if (apiError.status >= 500) {
    return "Сервер временно недоступен. Попробуйте позже.";
  }
  return "Не удалось выполнить запрос. Попробуйте позже.";
}

const FIELD_CODE_MESSAGES: Record<string, string> = {
  MISSING: "Обязательное поле.",
  STRING_TOO_SHORT: "Значение слишком короткое.",
  STRING_TOO_LONG: "Значение слишком длинное.",
  TOO_SHORT: "Значение слишком короткое.",
  TOO_LONG: "Значение слишком длинное.",
  VALUE_ERROR: "Некорректное значение.",
};

/** Map server field-validation details onto form field messages. */
export function fieldErrorsFrom(error: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  for (const detail of toApiError(error).details) {
    if (!detail.field) {
      continue;
    }
    result[detail.field] =
      (detail.code && FIELD_CODE_MESSAGES[detail.code]) ||
      detail.message ||
      "Некорректное значение.";
  }
  return result;
}
