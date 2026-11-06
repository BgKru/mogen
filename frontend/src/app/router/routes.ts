export const ROUTES = {
  home: "/",
  login: "/login",
  register: "/register",
  dashboard: "/dashboard",
  createProject: "/projects/new",
  projectDetails: (projectId: string) => `/projects/${projectId}`,
  projectResult: (projectId: string) => `/projects/${projectId}/result`,
} as const;
