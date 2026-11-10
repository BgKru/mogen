import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../shared/api/queryKeys";
import { appConfig } from "../../../shared/config";
import { getProjectProcessingStatus, startGeneration } from "../api/generationApi";

const ACTIVE_STATUSES: string[] = ["PENDING", "PROCESSING"];

function isActive(status: string | undefined): boolean {
  return status !== undefined && ACTIVE_STATUSES.includes(status);
}

/** Persisted status with polling only while the task is active. */
export function useProjectProcessingStatus(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.generationStatus(projectId ?? ""),
    queryFn: () => getProjectProcessingStatus(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) {
        return false;
      }
      const active = isActive(data.projectStatus) || isActive(data.latestTask?.status);
      return active ? appConfig.taskPollIntervalMs : false;
    },
  });
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `generation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Start a fresh attempt; every manual retry uses a new idempotency key. */
export function useStartGeneration(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => startGeneration(projectId, newIdempotencyKey()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.generationStatus(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.project(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}
