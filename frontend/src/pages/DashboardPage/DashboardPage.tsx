import { useState } from "react";
import { useNavigate } from "react-router";

import { ROUTES } from "../../app/router/routes";
import { useToast } from "../../app/providers/toast-context";
import { ProjectCard } from "../../features/projects/components/ProjectCard";
import { useDeleteProject, useProjects } from "../../features/projects/hooks/useProjects";
import { userMessageFor } from "../../shared/api/errors";
import { Alert } from "../../shared/components/Alert";
import { Button } from "../../shared/components/Button";
import { ConfirmDialog } from "../../shared/components/ConfirmDialog";
import { EmptyState } from "../../shared/components/EmptyState";
import { PageHeader } from "../../shared/components/PageHeader";
import { Spinner } from "../../shared/components/Spinner";
import type { Project } from "../../shared/types/api";

export function DashboardPage() {
  const projectsQuery = useProjects();
  const deleteMutation = useDeleteProject();
  const { notify } = useToast();
  const navigate = useNavigate();
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);

  function handleConfirmDelete() {
    if (!projectToDelete) {
      return;
    }
    deleteMutation.mutate(projectToDelete.id, {
      onSuccess: () => {
        notify("Проект удалён.", "success");
        setProjectToDelete(null);
      },
      onError: (error) => {
        notify(userMessageFor(error), "error");
      },
    });
  }

  const projects = projectsQuery.data?.items ?? [];
  const totalCount = projectsQuery.data?.totalCount ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Мои проекты"
        description="Все ваши проекты генерации объектов и реконструкции сцен."
        actions={<Button onClick={() => navigate(ROUTES.createProject)}>Создать проект</Button>}
      />

      {projectsQuery.isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner className="h-8 w-8" label="Загрузка проектов" />
        </div>
      ) : projectsQuery.isError ? (
        <div className="space-y-3">
          <Alert tone="error" title="Не удалось загрузить проекты">
            {userMessageFor(projectsQuery.error)}
          </Alert>
          <Button variant="secondary" onClick={() => void projectsQuery.refetch()}>
            Повторить
          </Button>
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          title="Пока нет проектов"
          description="Начните с фотографии объекта или нескольких снимков локации — мы создадим из них 3D-контент."
          icon={<span className="text-4xl text-accent">◈</span>}
          action={<Button onClick={() => navigate(ROUTES.createProject)}>Создать проект</Button>}
        />
      ) : (
        <>
          <p className="text-sm text-text-secondary">Всего проектов: {totalCount}</p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} onDelete={setProjectToDelete} />
            ))}
          </div>
        </>
      )}

      <ConfirmDialog
        open={projectToDelete !== null}
        title="Удалить проект?"
        description={
          <>
            Проект «{projectToDelete?.name}» и его файлы будут удалены. Это действие нельзя
            отменить.
          </>
        }
        isLoading={deleteMutation.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setProjectToDelete(null)}
      />
    </div>
  );
}
