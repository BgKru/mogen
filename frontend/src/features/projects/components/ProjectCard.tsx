import { Link } from "react-router";

import { ProjectStatusBadge, ProjectTypeBadge } from "../../../shared/components/ProjectBadges";
import { formatDate } from "../../../shared/lib/format";
import type { Project } from "../../../shared/types/api";
import { ROUTES } from "../../../app/router/routes";
import { ProjectPreview } from "./ProjectPreview";

interface ProjectCardProps {
  project: Project;
  onDelete: (project: Project) => void;
}

export function ProjectCard({ project, onDelete }: ProjectCardProps) {
  return (
    <article className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface transition hover:border-accent/50">
      <Link
        to={ROUTES.projectDetails(project.id)}
        className="flex flex-1 flex-col focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
        aria-label={`Открыть проект ${project.name}`}
      >
        <div className="h-32 border-b border-border bg-background/40 p-4">
          <ProjectPreview type={project.type} />
        </div>
        <div className="flex flex-1 flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <ProjectTypeBadge type={project.type} />
            <ProjectStatusBadge status={project.status} />
          </div>
          <h3 className="line-clamp-2 text-base font-semibold text-text-primary">{project.name}</h3>
          <p className="mt-auto text-xs text-text-secondary">
            Создан {formatDate(project.createdAt)} · Изображений: {project.sourceImageCount}
          </p>
        </div>
      </Link>
      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
        <span
          className={`text-xs font-medium ${project.resultAvailable ? "text-success" : "text-text-secondary"}`}
        >
          {project.resultAvailable ? "3D-результат доступен" : "Результат не создан"}
        </span>
        <button
          type="button"
          onClick={() => onDelete(project)}
          className="rounded-md px-2 py-1 text-xs font-medium text-error transition hover:bg-error/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-error"
          aria-label={`Удалить проект ${project.name}`}
        >
          Удалить
        </button>
      </div>
    </article>
  );
}
