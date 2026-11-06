import type {
  Project,
  ProjectCurrentResult,
  ProjectImage,
  ProjectImagePage,
  ProjectLatestTask,
  ProjectPage,
  ProjectStatus,
  ProjectType,
  User,
} from "../types/api";
import type {
  ProjectCurrentResultDto,
  ProjectDto,
  ProjectImageDto,
  ProjectImageListDto,
  ProjectLatestTaskDto,
  ProjectListDto,
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
