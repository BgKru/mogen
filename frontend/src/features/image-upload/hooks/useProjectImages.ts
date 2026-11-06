import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../shared/api/queryKeys";
import { deleteProjectImage, listProjectImages, uploadProjectImage } from "../api/imagesApi";

export function useProjectImages(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.projectImages(projectId ?? ""),
    queryFn: () => listProjectImages(projectId as string),
    enabled: Boolean(projectId),
  });
}

export function useUploadProjectImage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, onProgress }: { file: File; onProgress?: (percent: number) => void }) =>
      uploadProjectImage(projectId, file, onProgress),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectImages(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}

export function useDeleteProjectImage(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (imageId: string) => deleteProjectImage(projectId, imageId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectImages(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}
