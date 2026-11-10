/**
 * Wire-format DTOs.
 *
 * The backend contract (api_contracts.md) uses snake_case. Frontend domain
 * models are camelCase; the mappers in `mappers.ts` are the only place where
 * the two representations meet.
 */

export interface UserDto {
  id: string;
  email: string;
  created_at: string;
}

export interface AuthResponseDto {
  user: UserDto;
}

export interface CsrfResponseDto {
  csrf_token: string;
}

export interface ProjectCurrentResultDto {
  id: string;
  format: string;
  file_size_bytes: number;
  created_at: string;
}

export interface ProjectLatestTaskDto {
  id: string;
  status: string;
}

export interface ProjectDto {
  id: string;
  name: string;
  type: string;
  status: string;
  source_image_count: number;
  result_available: boolean;
  current_result: ProjectCurrentResultDto | null;
  latest_task: ProjectLatestTaskDto | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectListDto {
  items: ProjectDto[];
  total_count: number;
  limit: number;
  offset: number;
}

export interface ProjectImageDto {
  id: string;
  project_id: string;
  original_filename: string;
  mime_type: string;
  file_size_bytes: number;
  width: number;
  height: number;
  position: number;
  created_at: string;
}

export interface ProjectImageListDto {
  items: ProjectImageDto[];
  total_count: number;
}

export interface GenerationTaskDto {
  id: string;
  project_id: string;
  task_type: string;
  status: string;
  stage: string | null;
  progress_percent: number | null;
  status_message: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface GenerationTaskSummaryDto {
  id: string;
  task_type: string;
  status: string;
  stage: string | null;
  progress_percent: number | null;
  status_message: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface GenerationStartDto {
  task: GenerationTaskDto;
}

export interface ProjectProcessingStatusDto {
  project_id: string;
  project_status: string;
  result_available: boolean;
  latest_task: GenerationTaskSummaryDto | null;
}

export interface GenerationResultDto {
  id: string;
  project_id: string;
  task_id: string;
  format: string;
  mime_type: string;
  file_size_bytes: number;
  metadata: Record<string, unknown>;
  is_current: boolean;
  created_at: string;
}

export interface ApiErrorDetailDto {
  field?: string | null;
  code?: string;
  message: string;
}

export interface ApiErrorDto {
  error: {
    code: string;
    message: string;
    details?: unknown;
    request_id?: string | null;
  };
}
