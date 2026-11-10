import { useEffect, useRef } from "react";
import { Link } from "react-router";

import { ROUTES } from "../../../app/router/routes";
import { userMessageFor } from "../../../shared/api/errors";
import { Alert } from "../../../shared/components/Alert";
import { Button } from "../../../shared/components/Button";
import { Spinner } from "../../../shared/components/Spinner";
import { appConfig } from "../../../shared/config";
import { formatFileSize } from "../../../shared/lib/format";
import { GENERATION_STAGE_LABELS, generationErrorMessage } from "../../../shared/lib/labels";
import type { Project, ProjectStatus } from "../../../shared/types/api";
import { projectDownloadUrl } from "../api/generationApi";
import { useProjectProcessingStatus, useStartGeneration } from "../hooks/useGeneration";

const TERMINAL_PROJECT_STATUSES: ProjectStatus[] = ["COMPLETED", "FAILED"];

function isActiveStatus(status: string | null | undefined): boolean {
  return status === "PENDING" || status === "PROCESSING";
}

interface GenerationPanelProps {
  project: Project;
  imageCount: number;
  onStatusSettled?: () => void;
}

/**
 * Generation controls and real status display (roadmap 5.9 and 6.9).
 *
 * The panel never invents progress: it renders only the persisted stage,
 * percentage and error fields returned by `GET /projects/{id}/status`. Object
 * generation and scene reconstruction share the same persisted workflow; the
 * panel only differs in the readiness rule and the capture guidance.
 */
export function GenerationPanel({ project, imageCount, onStatusSettled }: GenerationPanelProps) {
  const statusQuery = useProjectProcessingStatus(project.id);
  const startMutation = useStartGeneration(project.id);
  const settledRef = useRef<string | null>(null);

  const isObject = project.type === "OBJECT";
  const status = statusQuery.data;
  const effectiveProjectStatus = status?.projectStatus ?? project.status;
  const resultAvailable = status?.resultAvailable ?? project.resultAvailable;
  const task = status?.latestTask ?? null;
  const active = isActiveStatus(effectiveProjectStatus) || isActiveStatus(task?.status);
  const imageReady = isObject ? imageCount === 1 : imageCount >= appConfig.minSceneImages;

  useEffect(() => {
    if (!status || !TERMINAL_PROJECT_STATUSES.includes(status.projectStatus)) {
      return;
    }
    const marker = `${status.projectStatus}:${status.resultAvailable}`;
    if (settledRef.current === marker) {
      return;
    }
    settledRef.current = marker;
    onStatusSettled?.();
  }, [status, onStatusSettled]);

  const stageLabel = task?.stage ? (GENERATION_STAGE_LABELS[task.stage] ?? task.stage) : null;
  const errorMessage =
    task?.status === "FAILED" ? generationErrorMessage(task.errorCode, task.errorMessage) : null;

  const buttonLabel = active
    ? "Идёт генерация…"
    : resultAvailable
      ? "Сгенерировать заново"
      : effectiveProjectStatus === "FAILED"
        ? "Повторить генерацию"
        : isObject
          ? "Создать 3D-модель"
          : "Реконструировать сцену";

  return (
    <section
      className="h-fit rounded-2xl border border-border bg-surface p-5"
      aria-labelledby="generation-heading"
    >
      <h2 id="generation-heading" className="text-lg font-semibold text-text-primary">
        Генерация
      </h2>

      <dl className="mt-3 space-y-2 text-sm">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-text-secondary">Тип</dt>
          <dd className="text-right font-medium text-text-primary">
            {isObject ? "Объект по фотографии" : "Сцена по фотографиям"}
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-text-secondary">Результат</dt>
          <dd
            className={`text-right font-medium ${
              resultAvailable ? "text-success" : "text-text-secondary"
            }`}
          >
            {resultAvailable ? "Готов" : "Ещё не создан"}
          </dd>
        </div>
      </dl>

      {!isObject && !imageReady ? (
        <p className="mt-4 text-xs text-text-secondary">
          Для реконструкции сцены нужно не меньше {appConfig.minSceneImages} фотографий. Загрузите
          их выше.
        </p>
      ) : null}

      {isObject && !imageReady ? (
        <p className="mt-4 text-xs text-text-secondary">
          Для генерации нужна ровно одна фотография объекта. Загрузите её выше.
        </p>
      ) : null}

      {statusQuery.isError ? (
        <Alert tone="error" className="mt-4" title="Не удалось получить статус">
          {userMessageFor(statusQuery.error)}
        </Alert>
      ) : null}

      {startMutation.isError ? (
        <Alert tone="error" className="mt-4" title="Не удалось запустить генерацию">
          {userMessageFor(startMutation.error)}
        </Alert>
      ) : null}

      {active ? (
        <div className="mt-4 rounded-xl border border-accent/40 bg-accent/5 p-4" aria-live="polite">
          <div className="flex items-center gap-2">
            <Spinner className="h-4 w-4" />
            <p className="text-sm font-medium text-text-primary">{stageLabel ?? "Обработка"}</p>
          </div>
          {task?.statusMessage ? (
            <p className="mt-1 text-xs text-text-secondary">{task.statusMessage}</p>
          ) : null}
          {task?.progressPercent != null ? (
            <div
              className="mt-3 h-2 overflow-hidden rounded-full bg-background"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={task.progressPercent}
              aria-label="Прогресс генерации"
            >
              <div
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${task.progressPercent}%` }}
              />
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-text-secondary">
              Точный процент недоступен — этап обработки показан по данным воркера.
            </p>
          )}
        </div>
      ) : null}

      {errorMessage ? (
        <Alert tone="error" className="mt-4" title="Генерация не удалась">
          <p>{errorMessage}</p>
          {task?.errorCode ? (
            <p className="mt-1 text-[11px] opacity-70">Код: {task.errorCode}</p>
          ) : null}
        </Alert>
      ) : null}

      {resultAvailable && !active ? (
        <div className="mt-4 rounded-xl border border-success/40 bg-success/5 p-4">
          <p className="text-sm font-medium text-text-primary">
            {isObject ? "3D-модель готова" : "Сцена готова"}
          </p>
          {project.currentResult ? (
            <p className="mt-1 text-xs text-text-secondary">
              {project.currentResult.format} · {formatFileSize(project.currentResult.fileSizeBytes)}
            </p>
          ) : null}
          <a
            href={projectDownloadUrl(project.id)}
            download
            className="mt-3 inline-flex w-full items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Скачать GLB
          </a>
          <Link
            to={ROUTES.projectResult(project.id)}
            className="mt-2 inline-flex w-full items-center justify-center rounded-lg border border-border bg-elevated px-4 py-2 text-sm font-medium text-text-primary transition hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Открыть в 3D
          </Link>
        </div>
      ) : null}

      <Button
        className="mt-5 w-full"
        onClick={() => startMutation.mutate()}
        disabled={!imageReady || active || startMutation.isPending}
        isLoading={startMutation.isPending || active}
      >
        {buttonLabel}
      </Button>

      {isObject ? (
        <p className="mt-3 text-xs text-text-secondary">
          Модель восстанавливается по одной фотографии, поэтому невидимые стороны достраиваются
          приблизительно. Для лучшего результата используйте ровный фон.
        </p>
      ) : (
        <p className="mt-3 text-xs text-text-secondary">
          Снимайте сцену с разных точек, двигаясь вокруг неё, с большим перекрытием кадров и ровным
          освещением. Минимальное число фотографий не гарантирует успешную реконструкцию.
        </p>
      )}
    </section>
  );
}
