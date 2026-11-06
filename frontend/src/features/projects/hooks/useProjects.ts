import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../shared/api/queryKeys";
import type { ProjectPage } from "../../../shared/types/api";
import { createProject, deleteProject, getProject, listProjects } from "../api/projectsApi";

export const PROJECTS_PAGE_LIMIT = 100;

export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projectList({ limit: PROJECTS_PAGE_LIMIT }),
    queryFn: () => listProjects({ limit: PROJECTS_PAGE_LIMIT }),
  });
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.project(projectId ?? ""),
    queryFn: () => getProject(projectId as string),
    enabled: Boolean(projectId),
  });
}

export function useCreateProject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.setQueryData(queryKeys.project(project.id), project);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}

interface DeleteContext {
  previous?: ProjectPage;
}

export function useDeleteProject() {
  const queryClient = useQueryClient();
  const listKey = queryKeys.projectList({ limit: PROJECTS_PAGE_LIMIT });
  return useMutation<void, unknown, string, DeleteContext>({
    mutationFn: deleteProject,
    onMutate: async (projectId) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<ProjectPage>(listKey);
      if (previous) {
        queryClient.setQueryData<ProjectPage>(listKey, {
          ...previous,
          items: previous.items.filter((project) => project.id !== projectId),
          totalCount: Math.max(0, previous.totalCount - 1),
        });
      }
      return { previous };
    },
    onError: (_error, _projectId, context) => {
      if (context?.previous) {
        queryClient.setQueryData(listKey, context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
    },
  });
}
