import { apiClient, apiUrl } from "../../../shared/api/client";
import type { GenerationStartDto, ProjectProcessingStatusDto } from "../../../shared/api/dto";
import { mapGenerationTask, mapProjectProcessingStatus } from "../../../shared/api/mappers";
import type { GenerationTask, ProjectProcessingStatus } from "../../../shared/types/api";

/** Start (or idempotently repeat) object generation for a project. */
export async function startGeneration(
  projectId: string,
  idempotencyKey: string,
): Promise<GenerationTask> {
  const { data } = await apiClient.post<GenerationStartDto>(
    `/projects/${projectId}/generate`,
    {},
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
  return mapGenerationTask(data.task);
}

/** Read the persisted project/task status; polling is layered on top. */
export async function getProjectProcessingStatus(
  projectId: string,
): Promise<ProjectProcessingStatus> {
  const { data } = await apiClient.get<ProjectProcessingStatusDto>(`/projects/${projectId}/status`);
  return mapProjectProcessingStatus(data);
}

/** Same-origin download URL; the browser sends the session cookie. */
export function projectDownloadUrl(projectId: string): string {
  return apiUrl(`/projects/${projectId}/download`);
}
