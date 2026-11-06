import { apiClient } from "../../../shared/api/client";
import { mapProjectImage, mapProjectImagePage } from "../../../shared/api/mappers";
import type { ProjectImageDto, ProjectImageListDto } from "../../../shared/api/dto";
import type { ProjectImage, ProjectImagePage } from "../../../shared/types/api";

/** Absolute or proxied URL of an image's private content endpoint. */
export function projectImageContentUrl(projectId: string, imageId: string): string {
  return apiClient.getUri({ url: `/projects/${projectId}/images/${imageId}/content` });
}

export async function listProjectImages(projectId: string): Promise<ProjectImagePage> {
  const { data } = await apiClient.get<ProjectImageListDto>(`/projects/${projectId}/images`);
  return mapProjectImagePage(data);
}

export async function uploadProjectImage(
  projectId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<ProjectImage> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<ProjectImageDto>(
    `/projects/${projectId}/images`,
    formData,
    {
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    },
  );
  return mapProjectImage(data);
}

export async function deleteProjectImage(projectId: string, imageId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}/images/${imageId}`);
}
