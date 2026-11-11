import { describe, expect, it } from "vitest";

import {
  mapGenerationResult,
  mapGenerationTask,
  mapGenerationTaskSummary,
  mapProject,
  mapProjectImage,
  mapProjectImagePage,
  mapProjectPage,
  mapProjectProcessingStatus,
  mapUser,
} from "./mappers";
import type {
  GenerationResultDto,
  GenerationTaskDto,
  GenerationTaskSummaryDto,
  ProjectDto,
  ProjectImageDto,
  ProjectProcessingStatusDto,
  UserDto,
} from "./dto";

const CREATED_AT = "2026-11-10T10:00:00Z";

const userDto: UserDto = {
  id: "user-1",
  email: "user@example.com",
  created_at: CREATED_AT,
};

const projectDto: ProjectDto = {
  id: "project-1",
  name: "Project",
  type: "OBJECT",
  status: "COMPLETED",
  source_image_count: 1,
  result_available: true,
  current_result: {
    id: "result-1",
    format: "GLB",
    file_size_bytes: 4096,
    created_at: CREATED_AT,
  },
  latest_task: { id: "task-1", status: "COMPLETED" },
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
};

const imageDto: ProjectImageDto = {
  id: "image-1",
  project_id: "project-1",
  original_filename: "photo.jpg",
  mime_type: "image/jpeg",
  file_size_bytes: 2048,
  width: 640,
  height: 480,
  position: 0,
  created_at: CREATED_AT,
};

const taskSummaryDto: GenerationTaskSummaryDto = {
  id: "task-1",
  task_type: "SCENE",
  status: "FAILED",
  stage: "SPARSE_RECONSTRUCTION",
  progress_percent: 40,
  status_message: "Reconstructing",
  error_code: "INSUFFICIENT_REGISTERED_IMAGES",
  error_message: "Not enough registered images.",
  created_at: CREATED_AT,
  started_at: CREATED_AT,
  finished_at: CREATED_AT,
};

const taskDto: GenerationTaskDto = { ...taskSummaryDto, project_id: "project-1" };

const resultDto: GenerationResultDto = {
  id: "result-1",
  project_id: "project-1",
  task_id: "task-1",
  format: "GLB",
  mime_type: "model/gltf-binary",
  file_size_bytes: 4096,
  metadata: { vertices_count: 100 },
  is_current: true,
  created_at: CREATED_AT,
};

describe("API DTO mappers", () => {
  it("maps a user to camelCase", () => {
    expect(mapUser(userDto)).toEqual({
      id: "user-1",
      email: "user@example.com",
      createdAt: CREATED_AT,
    });
  });

  it("maps a project including its current result and latest task", () => {
    expect(mapProject(projectDto)).toEqual({
      id: "project-1",
      name: "Project",
      type: "OBJECT",
      status: "COMPLETED",
      sourceImageCount: 1,
      resultAvailable: true,
      currentResult: {
        id: "result-1",
        format: "GLB",
        fileSizeBytes: 4096,
        createdAt: CREATED_AT,
      },
      latestTask: { id: "task-1", status: "COMPLETED" },
      createdAt: CREATED_AT,
      updatedAt: CREATED_AT,
    });
  });

  it("maps a project without a result or task to nulls", () => {
    const mapped = mapProject({
      ...projectDto,
      current_result: null,
      latest_task: null,
    });

    expect(mapped.currentResult).toBeNull();
    expect(mapped.latestTask).toBeNull();
  });

  it("maps a paginated project list", () => {
    const page = mapProjectPage({
      items: [projectDto],
      total_count: 1,
      limit: 20,
      offset: 0,
    });

    expect(page.totalCount).toBe(1);
    expect(page.items).toHaveLength(1);
    expect(page.items[0].name).toBe("Project");
  });

  it("maps image metadata", () => {
    expect(mapProjectImage(imageDto)).toEqual({
      id: "image-1",
      projectId: "project-1",
      originalFilename: "photo.jpg",
      mimeType: "image/jpeg",
      fileSizeBytes: 2048,
      width: 640,
      height: 480,
      position: 0,
      createdAt: CREATED_AT,
    });
  });

  it("maps an image listing", () => {
    const page = mapProjectImagePage({ items: [imageDto], total_count: 1 });

    expect(page.totalCount).toBe(1);
    expect(page.items[0].originalFilename).toBe("photo.jpg");
  });

  it("maps a task summary without a project id", () => {
    expect(mapGenerationTaskSummary(taskSummaryDto)).toEqual({
      id: "task-1",
      taskType: "SCENE",
      status: "FAILED",
      stage: "SPARSE_RECONSTRUCTION",
      progressPercent: 40,
      statusMessage: "Reconstructing",
      errorCode: "INSUFFICIENT_REGISTERED_IMAGES",
      errorMessage: "Not enough registered images.",
      createdAt: CREATED_AT,
      startedAt: CREATED_AT,
      finishedAt: CREATED_AT,
    });
  });

  it("maps a full task with its project id", () => {
    const task = mapGenerationTask(taskDto);

    expect(task.projectId).toBe("project-1");
    expect(task.taskType).toBe("SCENE");
  });

  it("maps the persisted processing status", () => {
    const dto: ProjectProcessingStatusDto = {
      project_id: "project-1",
      project_status: "PROCESSING",
      result_available: false,
      latest_task: taskSummaryDto,
    };

    const status = mapProjectProcessingStatus(dto);

    expect(status.projectId).toBe("project-1");
    expect(status.projectStatus).toBe("PROCESSING");
    expect(status.latestTask?.id).toBe("task-1");
  });

  it("maps a processing status with no latest task", () => {
    const status = mapProjectProcessingStatus({
      project_id: "project-1",
      project_status: "CREATED",
      result_available: false,
      latest_task: null,
    });

    expect(status.latestTask).toBeNull();
  });

  it("maps current result metadata", () => {
    expect(mapGenerationResult(resultDto)).toEqual({
      id: "result-1",
      projectId: "project-1",
      taskId: "task-1",
      format: "GLB",
      mimeType: "model/gltf-binary",
      fileSizeBytes: 4096,
      metadata: { vertices_count: 100 },
      isCurrent: true,
      createdAt: CREATED_AT,
    });
  });
});
