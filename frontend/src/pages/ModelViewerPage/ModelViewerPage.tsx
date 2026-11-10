import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router";

import { ROUTES } from "../../app/router/routes";
import { useProjectProcessingStatus } from "../../features/generation/hooks/useGeneration";
import { ModelInfoPanel } from "../../features/model-viewer/components/ModelInfoPanel";
import { ModelViewer } from "../../features/model-viewer/components/ModelViewer";
import { useCurrentResult } from "../../features/model-viewer/hooks/useCurrentResult";
import { useModelLoader } from "../../features/model-viewer/hooks/useModelLoader";
import { useProject } from "../../features/projects/hooks/useProjects";
import { toApiError, userMessageFor } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queryKeys";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { Spinner } from "../../shared/components/Spinner";
import { isUuid } from "../../shared/lib/uuid";
import type { ProjectStatus } from "../../shared/types/api";

const LINK_CLASS =
  "inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

function isActiveStatus(status: string | null | undefined): boolean {
  return status === "PENDING" || status === "PROCESSING";
}

/**
 * Dedicated 3D result workspace (02_ui_ux_specification.md 4.7).
 *
 * The viewer is opened only for a validated current result served by the
 * existing result/download API. A failed regeneration keeps the previous
 * result visible; a project without a completed result gets an explanation
 * instead of an empty canvas.
 */
export function ModelViewerPage() {
  const { projectId } = useParams();
  const validId = isUuid(projectId);
  const id = validId ? (projectId as string) : undefined;
  const queryClient = useQueryClient();
  const projectQuery = useProject(id);
  const resultQuery = useCurrentResult(id);
  const statusQuery = useProjectProcessingStatus(id);
  const result = resultQuery.data ?? null;
  const loader = useModelLoader(id ?? "", Boolean(id && result), result?.id);
  const settledRef = useRef<string | null>(null);

  useEffect(() => {
    const status = statusQuery.data;
    if (!id || !status || status.projectStatus !== "COMPLETED") {
      return;
    }
    const marker = status.latestTask?.id ?? status.projectStatus;
    if (settledRef.current === marker) {
      return;
    }
    settledRef.current = marker;
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectResult(id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.project(id) });
  }, [id, queryClient, statusQuery.data]);

  if (!validId) {
    return (
      <Unavailable
        title="Проект не найден"
        description="Идентификатор проекта в адресе некорректен."
      />
    );
  }

  if (projectQuery.isLoading || resultQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner className="h-8 w-8" label="Загрузка результата" />
      </div>
    );
  }

  if (projectQuery.isError || !projectQuery.data) {
    const apiError = toApiError(projectQuery.error);
    if (apiError.status === 404) {
      return (
        <Unavailable
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

  if (resultQuery.isError) {
    return (
      <div className="space-y-3">
        <Alert tone="error" title="Не удалось загрузить результат">
          {userMessageFor(resultQuery.error)}
        </Alert>
        <Button variant="secondary" onClick={() => void resultQuery.refetch()}>
          Повторить
        </Button>
      </div>
    );
  }

  const project = projectQuery.data;
  const liveStatus = statusQuery.data;
  const effectiveStatus = (liveStatus?.projectStatus ?? project.status) as ProjectStatus;
  const latestTask = liveStatus?.latestTask ?? null;
  const isProcessing = isActiveStatus(effectiveStatus) || isActiveStatus(latestTask?.status);
  const displayProject = { ...project, status: effectiveStatus };

  if (!result) {
    return (
      <div className="space-y-4">
        <BackLink projectId={project.id} />
        <EmptyState
          title={isProcessing ? "Генерация выполняется" : "3D-результат ещё не создан"}
          description={
            isProcessing
              ? "Модель появится здесь после завершения обработки. Следить за этапами можно на странице проекта."
              : "Завершите генерацию модели на странице проекта, чтобы открыть её в 3D-просмотрщике."
          }
          action={
            <Link to={ROUTES.projectDetails(project.id)} className={LINK_CLASS}>
              Перейти к проекту
            </Link>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <BackLink projectId={project.id} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]">
        <div className="h-[58vh] min-h-[380px] lg:h-[calc(100vh-13rem)]">
          <ModelViewer
            model={loader.model}
            status={loader.status}
            stats={loader.stats}
            error={loader.error}
            onRetry={loader.reload}
          />
        </div>
        <ModelInfoPanel
          project={displayProject}
          result={result}
          stats={loader.stats}
          latestTask={latestTask}
          isProcessing={isProcessing}
        />
      </div>
    </div>
  );
}

function BackLink({ projectId }: { projectId: string }) {
  return (
    <Link
      to={ROUTES.projectDetails(projectId)}
      className="inline-flex text-sm font-medium text-text-secondary transition hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      ← К проекту
    </Link>
  );
}

function Unavailable({ title, description }: { title: string; description: string }) {
  return (
    <div className="space-y-4">
      <EmptyState title={title} description={description} />
      <div className="text-center">
        <Link to={ROUTES.dashboard} className="text-sm font-medium text-accent hover:underline">
          Вернуться к проектам
        </Link>
      </div>
    </div>
  );
}
