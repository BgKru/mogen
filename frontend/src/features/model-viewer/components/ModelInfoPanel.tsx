import { Link } from "react-router";

import { ROUTES } from "../../../app/router/routes";
import { projectDownloadUrl } from "../../generation/api/generationApi";
import { Alert } from "../../../shared/components/Alert";
import { ProjectStatusBadge, ProjectTypeBadge } from "../../../shared/components/ProjectBadges";
import { formatDate, formatFileSize, pluralizeImages } from "../../../shared/lib/format";
import { PROJECT_TYPE_LABELS } from "../../../shared/lib/labels";
import type { GenerationResult, GenerationTaskSummary, Project } from "../../../shared/types/api";
import type { ModelStats } from "../types/viewer.types";

interface ModelInfoPanelProps {
  project: Project;
  result: GenerationResult;
  stats: ModelStats | null;
  latestTask: GenerationTaskSummary | null;
  isProcessing: boolean;
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatCount(value: number | null): string {
  return value === null ? "—" : new Intl.NumberFormat("ru-RU").format(value);
}

/**
 * Result metadata panel (roadmap 7.4/7.6, 02_ui_ux_specification.md 4.7).
 *
 * Live measurements from the parsed model take precedence over the persisted
 * metadata; both describe the same validated asset. A failed regeneration is
 * reported without hiding the preserved current result.
 */
export function ModelInfoPanel({
  project,
  result,
  stats,
  latestTask,
  isProcessing,
}: ModelInfoPanelProps) {
  const meshes = stats?.meshes ?? metadataNumber(result.metadata, "meshes_count");
  const vertices = stats?.vertices ?? metadataNumber(result.metadata, "vertices_count");
  const triangles = stats?.triangles ?? metadataNumber(result.metadata, "faces_count");
  const materials = stats?.materials ?? metadataNumber(result.metadata, "materials_count");
  const textures = stats?.textures ?? metadataNumber(result.metadata, "textures_count");

  return (
    <aside className="flex h-fit flex-col gap-4 rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <ProjectTypeBadge type={project.type} />
        <ProjectStatusBadge status={project.status} />
      </div>

      <div>
        <h1 className="text-xl font-semibold tracking-tight text-text-primary">{project.name}</h1>
        <p className="mt-1 text-xs text-text-secondary">
          {PROJECT_TYPE_LABELS[project.type]} · {pluralizeImages(project.sourceImageCount)}
        </p>
      </div>

      {isProcessing ? (
        <Alert tone="info" title="Идёт новая генерация">
          Показан текущий сохранённый результат. Он обновится после завершения обработки.
        </Alert>
      ) : null}

      {latestTask?.status === "FAILED" ? (
        <Alert tone="warning" title="Показан предыдущий результат">
          Последняя попытка генерации завершилась ошибкой. Текущий успешный результат сохранён и
          доступен для просмотра и скачивания.
        </Alert>
      ) : null}

      <dl className="space-y-2 text-sm">
        <InfoRow label="Формат" value={result.format || "GLB"} />
        <InfoRow label="Размер файла" value={formatFileSize(result.fileSizeBytes)} />
        <InfoRow label="Создан" value={formatDate(result.createdAt)} />
        <InfoRow label="Мешей" value={formatCount(meshes)} />
        <InfoRow label="Вершин" value={formatCount(vertices)} />
        <InfoRow label="Полигонов" value={formatCount(triangles)} />
        <InfoRow label="Материалов" value={formatCount(materials)} />
        <InfoRow label="Текстур" value={formatCount(textures)} />
      </dl>

      <div className="rounded-xl border border-success/40 bg-success/5 p-4">
        <p className="text-sm font-medium text-text-primary">Результат готов</p>
        <p className="mt-1 text-xs text-text-secondary">
          {stats?.hasTextures
            ? "Модель содержит встроенные текстуры."
            : stats?.hasVertexColors
              ? "Модель содержит вершинные цвета."
              : "Файл GLB проверен и доступен для скачивания."}
        </p>
        <a
          href={projectDownloadUrl(project.id)}
          download
          className="mt-3 inline-flex w-full items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Скачать GLB
        </a>
      </div>

      <Link
        to={ROUTES.projectDetails(project.id)}
        className="text-center text-sm font-medium text-accent hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Перейти к проекту
      </Link>
    </aside>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-text-secondary">{label}</dt>
      <dd className="text-right font-medium text-text-primary">{value}</dd>
    </div>
  );
}
