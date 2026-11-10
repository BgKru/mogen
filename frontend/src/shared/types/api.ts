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

/** Persisted generation task fields shared by the start and status responses. */
export interface GenerationTaskSummary {
  id: string;
  taskType: ProjectType;
  status: string;
  stage: string | null;
  progressPercent: number | null;
  statusMessage: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface GenerationTask extends GenerationTaskSummary {
  projectId: string;
}

/** The persisted project/task state returned by `GET /status`. */
export interface ProjectProcessingStatus {
  projectId: string;
  projectStatus: ProjectStatus;
  resultAvailable: boolean;
  latestTask: GenerationTaskSummary | null;
}

export interface GenerationResult {
  id: string;
  projectId: string;
  taskId: string;
  format: string;
  mimeType: string;
  fileSizeBytes: number;
  metadata: Record<string, unknown>;
  isCurrent: boolean;
  createdAt: string;
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
