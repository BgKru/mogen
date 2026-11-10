import type {
  GenerationResult,
  GenerationTask,
  GenerationTaskSummary,
  Project,
  ProjectCurrentResult,
  ProjectImage,
  ProjectImagePage,
  ProjectLatestTask,
  ProjectPage,
  ProjectProcessingStatus,
  ProjectStatus,
  ProjectType,
  User,
} from "../types/api";
import type {
  GenerationResultDto,
  GenerationTaskDto,
  GenerationTaskSummaryDto,
  ProjectCurrentResultDto,
  ProjectDto,
  ProjectImageDto,
  ProjectImageListDto,
  ProjectLatestTaskDto,
  ProjectListDto,
  ProjectProcessingStatusDto,
  UserDto,
} from "./dto";

/** Convert a backend user DTO into the frontend domain model. */
export function mapUser(dto: UserDto): User {
  return {
    id: dto.id,
    email: dto.email,
    createdAt: dto.created_at,
  };
}

function mapCurrentResult(dto: ProjectCurrentResultDto): ProjectCurrentResult {
  return {
    id: dto.id,
    format: dto.format,
    fileSizeBytes: dto.file_size_bytes,
    createdAt: dto.created_at,
  };
}

function mapLatestTask(dto: ProjectLatestTaskDto): ProjectLatestTask {
  return {
    id: dto.id,
    status: dto.status,
  };
}

/** Convert a backend project DTO into the frontend domain model. */
export function mapProject(dto: ProjectDto): Project {
  return {
    id: dto.id,
    name: dto.name,
    type: dto.type as ProjectType,
    status: dto.status as ProjectStatus,
    sourceImageCount: dto.source_image_count,
    resultAvailable: dto.result_available,
    currentResult: dto.current_result ? mapCurrentResult(dto.current_result) : null,
    latestTask: dto.latest_task ? mapLatestTask(dto.latest_task) : null,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

/** Convert a paginated project response. */
export function mapProjectPage(dto: ProjectListDto): ProjectPage {
  return {
    items: dto.items.map(mapProject),
    totalCount: dto.total_count,
    limit: dto.limit,
    offset: dto.offset,
  };
}

/** Convert a backend image DTO into the frontend domain model. */
export function mapProjectImage(dto: ProjectImageDto): ProjectImage {
  return {
    id: dto.id,
    projectId: dto.project_id,
    originalFilename: dto.original_filename,
    mimeType: dto.mime_type,
    fileSizeBytes: dto.file_size_bytes,
    width: dto.width,
    height: dto.height,
    position: dto.position,
    createdAt: dto.created_at,
  };
}

/** Convert a project image listing. */
export function mapProjectImagePage(dto: ProjectImageListDto): ProjectImagePage {
  return {
    items: dto.items.map(mapProjectImage),
    totalCount: dto.total_count,
  };
}

/** Convert a task summary embedded in the status response. */
export function mapGenerationTaskSummary(dto: GenerationTaskSummaryDto): GenerationTaskSummary {
  return {
    id: dto.id,
    taskType: dto.task_type as ProjectType,
    status: dto.status,
    stage: dto.stage,
    progressPercent: dto.progress_percent,
    statusMessage: dto.status_message,
    errorCode: dto.error_code,
    errorMessage: dto.error_message,
    createdAt: dto.created_at,
    startedAt: dto.started_at,
    finishedAt: dto.finished_at,
  };
}

/** Convert a full generation task returned when generation starts. */
export function mapGenerationTask(dto: GenerationTaskDto): GenerationTask {
  return {
    ...mapGenerationTaskSummary(dto),
    projectId: dto.project_id,
  };
}

/** Convert the persisted project/task processing status. */
export function mapProjectProcessingStatus(
  dto: ProjectProcessingStatusDto,
): ProjectProcessingStatus {
  return {
    projectId: dto.project_id,
    projectStatus: dto.project_status as ProjectStatus,
    resultAvailable: dto.result_available,
    latestTask: dto.latest_task ? mapGenerationTaskSummary(dto.latest_task) : null,
  };
}

/** Convert current result metadata. */
export function mapGenerationResult(dto: GenerationResultDto): GenerationResult {
  return {
    id: dto.id,
    projectId: dto.project_id,
    taskId: dto.task_id,
    format: dto.format,
    mimeType: dto.mime_type,
    fileSizeBytes: dto.file_size_bytes,
    metadata: dto.metadata,
    isCurrent: dto.is_current,
    createdAt: dto.created_at,
  };
}
