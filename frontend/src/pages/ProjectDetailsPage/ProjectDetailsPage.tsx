import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { useToast } from "../../app/providers/toast-context";
import { ROUTES } from "../../app/router/routes";
import { GenerationPanel } from "../../features/generation/components/GenerationPanel";
import { useProjectProcessingStatus } from "../../features/generation/hooks/useGeneration";
import { projectImageContentUrl } from "../../features/image-upload/api/imagesApi";
import { ImageDropzone } from "../../features/image-upload/components/ImageDropzone";
import { useImageSelection } from "../../features/image-upload/hooks/useImageSelection";
import {
  useDeleteProjectImage,
  useProjectImages,
  useUploadProjectImage,
} from "../../features/image-upload/hooks/useProjectImages";
import { useDeleteProject, useProject } from "../../features/projects/hooks/useProjects";
import { toApiError, userMessageFor } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queryKeys";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog";
import { EmptyState } from "../../shared/components/EmptyState";
import { ProjectStatusBadge, ProjectTypeBadge } from "../../shared/components/ProjectBadges";
import { Spinner } from "../../shared/components/Spinner";
import { appConfig } from "../../shared/config";
import { formatDate, formatFileSize, pluralizeImages } from "../../shared/lib/format";
import { isUuid } from "../../shared/lib/uuid";
import type { ProjectImage } from "../../shared/types/api";

interface LocationState {
  uploadFailures?: string[];
}

interface UploadState {
  index: number;
  total: number;
  percent: number;
  filename: string;
}

export function ProjectDetailsPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { notify } = useToast();
  const validId = isUuid(projectId);
  const queryClient = useQueryClient();
  const projectQuery = useProject(validId ? projectId : undefined);
  const processingQuery = useProjectProcessingStatus(validId ? projectId : undefined);
  const imagesQuery = useProjectImages(validId ? projectId : undefined);
  const deleteProjectMutation = useDeleteProject();
  const deleteImageMutation = useDeleteProjectImage(projectId ?? "");
  const uploadMutation = useUploadProjectImage(projectId ?? "");

  const project = projectQuery.data;
  const images = imagesQuery.data?.items ?? [];
  const isObject = project?.type === "OBJECT";
  const remainingSlots = isObject
    ? images.length === 0
      ? 1
      : 0
    : Math.max(0, appConfig.maxSceneImages - images.length);
  const selection = useImageSelection({
    mode: isObject ? "single" : "multiple",
    maxFiles: isObject ? 1 : Math.max(1, remainingSlots),
  });
  const {
    items,
    errors: selectionErrors,
    addFiles,
    remove,
    clear: clearSelection,
    dismissErrors,
  } = selection;

  const [projectToDelete, setProjectToDelete] = useState(false);
  const [imageToDelete, setImageToDelete] = useState<ProjectImage | null>(null);
  const [uploadState, setUploadState] = useState<UploadState | null>(null);
  const [dismissedFailures, setDismissedFailures] = useState(false);
  const uploadFailures = (location.state as LocationState | null)?.uploadFailures ?? [];

  // The generation panel polls the persisted status while a task is active;
  // once a terminal state arrives the project and image queries are refreshed.
  const handleStatusSettled = useCallback(() => {
    if (!validId) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId as string) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
  }, [projectId, queryClient, validId]);

  useEffect(() => {
    clearSelection();
  }, [clearSelection, isObject]);

  if (!validId) {
    return (
      <ProjectUnavailable
        title="Проект не найден"
        description="Идентификатор проекта в адресе некорректен."
      />
    );
  }

  if (projectQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="h-8 w-8" label="Загрузка проекта" />
      </div>
    );
  }

  if (projectQuery.isError || !project) {
    const apiError = toApiError(projectQuery.error);
    if (apiError.status === 404) {
      return (
        <ProjectUnavailable
          title="Проект не найден"
          description="Проект не существует, удалён или недоступен."
        />
      );
    }
    return (
      <div className="space-y-3">
        <Alert tone="error" title="Не удалось загрузить проект">
          {userMessageFor(projectQuery.error)}
        </Alert>
        <Button variant="secondary" onClick={() => void projectQuery.refetch()}>
          Повторить
        </Button>
      </div>
    );
  }

  const liveStatus = processingQuery.data;
  const effectiveProjectStatus = liveStatus?.projectStatus ?? project.status;
  const activeTaskStatus = liveStatus?.latestTask?.status ?? project.latestTask?.status;
  const isProcessing =
    effectiveProjectStatus === "PENDING" ||
    effectiveProjectStatus === "PROCESSING" ||
    activeTaskStatus === "PENDING" ||
    activeTaskStatus === "PROCESSING";
  const canModify = !isProcessing;
  const canAddImages = canModify && remainingSlots > 0;

  async function handleUpload() {
    if (!project || items.length === 0 || !canAddImages) {
      return;
    }
    const failures: string[] = [];
    const total = items.length;
    for (const [index, item] of items.entries()) {
      setUploadState({
        index: index + 1,
        total,
        percent: 0,
        filename: item.file.name,
      });
      try {
        await uploadMutation.mutateAsync({
          file: item.file,
          onProgress: (percent) => {
            setUploadState((current) => (current ? { ...current, percent } : current));
          },
        });
        remove(item.id);
      } catch (error) {
        failures.push(`${item.file.name}: ${userMessageFor(error)}`);
      }
    }
    setUploadState(null);
    if (failures.length > 0) {
      notify(`Не удалось загрузить: ${failures.join("; ")}`, "error");
    } else {
      clearSelection();
      notify("Изображения загружены.", "success");
    }
  }

  function handleDeleteImage() {
    if (!imageToDelete) {
      return;
    }
    deleteImageMutation.mutate(imageToDelete.id, {
      onSuccess: () => {
        notify("Изображение удалено.", "success");
        setImageToDelete(null);
      },
      onError: (error) => {
        notify(userMessageFor(error), "error");
      },
    });
  }

  function handleDeleteProject() {
    if (!project) {
      return;
    }
    deleteProjectMutation.mutate(project.id, {
      onSuccess: () => {
        notify("Проект удалён.", "success");
        navigate(ROUTES.dashboard, { replace: true });
      },
      onError: (error) => {
        notify(userMessageFor(error), "error");
      },
    });
  }

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.dashboard}
        className="inline-flex text-sm font-medium text-text-secondary transition hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        ← Мои проекты
      </Link>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">
            {project.name}
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <ProjectTypeBadge type={project.type} />
            <ProjectStatusBadge status={project.status} />
            <span className="text-xs text-text-secondary">
              Создан {formatDate(project.createdAt)} · {pluralizeImages(project.sourceImageCount)}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {project.resultAvailable ? (
            <Link
              to={ROUTES.projectResult(project.id)}
              className="inline-flex items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-background transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Просмотреть 3D-модель
            </Link>
          ) : null}
          <Button variant="danger" onClick={() => setProjectToDelete(true)}>
            Удалить проект
          </Button>
        </div>
      </div>

      {uploadFailures.length > 0 && !dismissedFailures ? (
        <Alert tone="error" title="Часть изображений не загрузилась">
          <ul className="list-inside list-disc space-y-1">
            {uploadFailures.map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setDismissedFailures(true)}
            className="mt-2 text-xs font-medium underline"
          >
            Скрыть
          </button>
        </Alert>
      ) : null}

      {isProcessing ? (
        <Alert tone="info" title="Проект обрабатывается">
          Изменение изображений временно недоступно, пока выполняется генерация.
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <section className="rounded-2xl border border-border bg-surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-text-primary">Исходные изображения</h2>
            <span className="text-xs text-text-secondary">{pluralizeImages(images.length)}</span>
          </div>

          {imagesQuery.isError ? (
            <Alert tone="error" className="mt-4">
              {userMessageFor(imagesQuery.error)}
            </Alert>
          ) : imagesQuery.isLoading ? (
            <div className="flex justify-center py-10">
              <Spinner className="h-6 w-6" />
            </div>
          ) : images.length === 0 ? (
            <div className="mt-4 space-y-4">
              <p className="text-sm text-text-secondary">
                У проекта пока нет изображений. Добавьте фотографии, чтобы подготовить его к
                генерации.
              </p>
              {canModify ? (
                <>
                  {selectionErrors.length > 0 ? (
                    <Alert tone="error">
                      <ul className="list-inside list-disc space-y-1">
                        {selectionErrors.map((message) => (
                          <li key={message}>{message}</li>
                        ))}
                      </ul>
                      <button
                        type="button"
                        onClick={dismissErrors}
                        className="mt-2 text-xs font-medium underline"
                      >
                        Скрыть
                      </button>
                    </Alert>
                  ) : null}
                  <ImageDropzone
                    mode={isObject ? "single" : "multiple"}
                    items={items}
                    onAdd={addFiles}
                    onRemove={remove}
                    disabled={uploadMutation.isPending}
                    maxFiles={isObject ? 1 : appConfig.maxSceneImages}
                  />
                  {items.length > 0 ? (
                    <Button
                      onClick={() => void handleUpload()}
                      isLoading={uploadMutation.isPending}
                    >
                      Загрузить изображения
                    </Button>
                  ) : null}
                </>
              ) : null}
            </div>
          ) : (
            <>
              <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                {images.map((image) => (
                  <li
                    key={image.id}
                    className="overflow-hidden rounded-xl border border-border bg-elevated"
                  >
                    <img
                      src={projectImageContentUrl(project.id, image.id)}
                      alt={image.originalFilename}
                      loading="lazy"
                      className="aspect-[4/3] w-full object-cover"
                    />
                    <div className="flex items-center justify-between gap-2 p-3">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium text-text-primary">
                          {image.originalFilename}
                        </p>
                        <p className="text-[11px] text-text-secondary">
                          {formatFileSize(image.fileSizeBytes)} · {image.width}×{image.height}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setImageToDelete(image)}
                        disabled={!canModify}
                        className="rounded-md px-2 py-1 text-xs font-medium text-error transition hover:bg-error/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-error disabled:cursor-not-allowed disabled:opacity-50"
                        aria-label={`Удалить изображение ${image.originalFilename}`}
                      >
                        Удалить
                      </button>
                    </div>
                  </li>
                ))}
              </ul>

              {isObject && images.length > 0 ? (
                <p className="mt-4 text-xs text-text-secondary">
                  Чтобы заменить фотографию объекта, удалите текущую и загрузите новую.
                </p>
              ) : null}

              {!isObject && canModify ? (
                <details className="mt-4 rounded-xl border border-border bg-background/40 p-4">
                  <summary className="cursor-pointer text-sm font-medium text-text-primary">
                    Добавить изображения
                  </summary>
                  <div className="mt-4 space-y-4">
                    {selectionErrors.length > 0 ? (
                      <Alert tone="error">
                        <ul className="list-inside list-disc space-y-1">
                          {selectionErrors.map((message) => (
                            <li key={message}>{message}</li>
                          ))}
                        </ul>
                        <button
                          type="button"
                          onClick={dismissErrors}
                          className="mt-2 text-xs font-medium underline"
                        >
                          Скрыть
                        </button>
                      </Alert>
                    ) : null}
                    <ImageDropzone
                      mode="multiple"
                      items={items}
                      onAdd={addFiles}
                      onRemove={remove}
                      disabled={uploadMutation.isPending}
                      maxFiles={remainingSlots}
                    />
                    {items.length > 0 ? (
                      <Button
                        onClick={() => void handleUpload()}
                        isLoading={uploadMutation.isPending}
                      >
                        Загрузить изображения
                      </Button>
                    ) : null}
                  </div>
                </details>
              ) : null}
            </>
          )}

          {uploadState ? (
            <div
              className="mt-4 rounded-xl border border-accent/40 bg-accent/5 p-4"
              aria-live="polite"
            >
              <p className="text-sm font-medium text-text-primary">
                Загрузка {uploadState.index} из {uploadState.total}: {uploadState.filename}
              </p>
              <div
                className="mt-2 h-2 overflow-hidden rounded-full bg-background"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={uploadState.percent}
                aria-label="Прогресс загрузки изображения"
              >
                <div
                  className="h-full rounded-full bg-accent transition-[width]"
                  style={{ width: `${uploadState.percent}%` }}
                />
              </div>
            </div>
          ) : null}
        </section>

        <GenerationPanel
          project={project}
          imageCount={images.length}
          onStatusSettled={handleStatusSettled}
        />
      </div>

      <ConfirmDialog
        open={imageToDelete !== null}
        title="Удалить изображение?"
        description={
          <>
            Изображение «{imageToDelete?.originalFilename}» будет удалено из проекта. Если оно
            использовалось в генерации, удаление может быть отклонено.
          </>
        }
        isLoading={deleteImageMutation.isPending}
        onConfirm={handleDeleteImage}
        onCancel={() => setImageToDelete(null)}
      />

      <ConfirmDialog
        open={projectToDelete}
        title="Удалить проект?"
        description={
          <>Проект «{project.name}» и его файлы будут удалены. Это действие нельзя отменить.</>
        }
        isLoading={deleteProjectMutation.isPending}
        onConfirm={handleDeleteProject}
        onCancel={() => setProjectToDelete(false)}
      />
    </div>
  );
}

function ProjectUnavailable({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-4">
      <EmptyState title={title} description={description} />
      <div className="text-center">
        <Link
          to={ROUTES.dashboard}
          className="text-sm font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Вернуться к проектам
        </Link>
      </div>
    </div>
  );
}
