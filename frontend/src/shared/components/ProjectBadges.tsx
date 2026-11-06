import { PROJECT_STATUS_LABELS, PROJECT_STATUS_TONES, PROJECT_TYPE_LABELS } from "../lib/labels";
import type { ProjectStatus, ProjectType } from "../types/api";

const STATUS_CLASSES = {
  neutral: "border-border bg-elevated text-text-secondary",
  info: "border-accent/40 bg-accent/10 text-accent",
  success: "border-success/40 bg-success/10 text-success",
  error: "border-error/40 bg-error/10 text-error",
} as const;

export function ProjectStatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${STATUS_CLASSES[PROJECT_STATUS_TONES[status]]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {PROJECT_STATUS_LABELS[status]}
    </span>
  );
}

export function ProjectTypeBadge({ type }: { type: ProjectType }) {
  return (
    <span className="inline-flex items-center rounded-full border border-border bg-elevated px-2.5 py-1 text-xs font-medium text-text-secondary">
      {PROJECT_TYPE_LABELS[type]}
    </span>
  );
}
