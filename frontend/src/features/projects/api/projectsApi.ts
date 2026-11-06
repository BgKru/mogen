import { apiClient } from "../../../shared/api/client";
import { mapProject, mapProjectPage } from "../../../shared/api/mappers";
import type { ProjectDto, ProjectListDto } from "../../../shared/api/dto";
import type { CreateProjectInput, Project, ProjectPage } from "../../../shared/types/api";

export interface ListProjectsParams {
  limit?: number;
  offset?: number;
}

export async function listProjects(params: ListProjectsParams = {}): Promise<ProjectPage> {
  const { data } = await apiClient.get<ProjectListDto>("/projects", { params });
  return mapProjectPage(data);
}

export async function getProject(projectId: string): Promise<Project> {
  const { data } = await apiClient.get<ProjectDto>(`/projects/${projectId}`);
  return mapProject(data);
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const { data } = await apiClient.post<ProjectDto>("/projects", input);
  return mapProject(data);
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiClient.delete(`/projects/${projectId}`);
}
