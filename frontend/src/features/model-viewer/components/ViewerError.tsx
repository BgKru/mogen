import { Button } from "../../../shared/components/Button";
import type { ViewerErrorCode, ViewerLoadError } from "../types/viewer.types";

const ERROR_MESSAGES: Record<ViewerErrorCode, string> = {
  DOWNLOAD_FAILED:
    "Не удалось получить файл модели с сервера. Проверьте соединение и попробуйте снова.",
  PARSE_FAILED:
    "Файл модели повреждён или имеет неподдерживаемый формат. Скачайте его и проверьте в другом просмотрщике.",
  EMPTY_MODEL: "В файле модели не найдено ни одной полигональной сетки.",
  UNSUPPORTED_ASSET: "Сервер вернул файл, который просмотрщик не поддерживает.",
  ASSET_TOO_LARGE:
    "Файл результата слишком большой для просмотра в браузере. Его можно скачать и открыть в настольном просмотрщике.",
  WEBGL_UNAVAILABLE:
    "Браузер не смог запустить рендеринг гауссовых сплатов (WebGL/GPU). Попробуйте другой браузер или видеокарту.",
};

interface ViewerErrorProps {
  error: ViewerLoadError | null;
  onRetry: () => void;
}

/** Readable failure state with an explicit retry action (FE-AC-13, UI-AC-14). */
export function ViewerError({ error, onRetry }: ViewerErrorProps) {
  const message = ERROR_MESSAGES[error?.code ?? "PARSE_FAILED"];
  return (
    <div
      role="alert"
      className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 bg-background/85 px-6 text-center"
    >
      <div className="max-w-md">
        <h2 className="text-lg font-semibold text-text-primary">Не удалось показать 3D-модель</h2>
        <p className="mt-2 text-sm text-text-secondary">{message}</p>
      </div>
      <Button variant="secondary" onClick={onRetry}>
        Повторить загрузку
      </Button>
    </div>
  );
}
