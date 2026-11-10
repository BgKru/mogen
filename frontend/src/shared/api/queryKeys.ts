/** Centralised query keys for TanStack Query. */
export const queryKeys = {
  currentUser: ["auth", "me"] as const,
  projects: ["projects"] as const,
  projectList: (params?: { limit?: number; offset?: number }) =>
    ["projects", "list", params ?? {}] as const,
  project: (projectId: string) => ["projects", projectId] as const,
  projectImages: (projectId: string) => ["projects", projectId, "images"] as const,
  generationStatus: (projectId: string) => ["projects", projectId, "generation-status"] as const,
  projectResult: (projectId: string) => ["projects", projectId, "result"] as const,
};
