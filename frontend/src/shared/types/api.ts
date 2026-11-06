export type ProjectType = "OBJECT" | "SCENE";

export type ProjectStatus =
  "CREATED" | "UPLOADING" | "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface User {
  id: string;
  email: string;
  createdAt: string;
}

export interface ProjectCurrentResult {
  id: string;
  format: string;
  fileSizeBytes: number;
  createdAt: string;
}

export interface ProjectLatestTask {
  id: string;
  status: string;
}

export interface Project {
  id: string;
  name: string;
  type: ProjectType;
  status: ProjectStatus;
  sourceImageCount: number;
  resultAvailable: boolean;
  currentResult: ProjectCurrentResult | null;
  latestTask: ProjectLatestTask | null;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectPage {
  items: Project[];
  totalCount: number;
  limit: number;
  offset: number;
}

export interface ProjectImage {
  id: string;
  projectId: string;
  originalFilename: string;
  mimeType: string;
  fileSizeBytes: number;
  width: number;
  height: number;
  position: number;
  createdAt: string;
}

export interface ProjectImagePage {
  items: ProjectImage[];
  totalCount: number;
}

export interface CreateProjectInput {
  name: string;
  type: ProjectType;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  email: string;
  password: string;
}
