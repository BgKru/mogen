import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/errors";
import type { GenerationResult, Project } from "../../shared/types/api";
import { renderWithProviders } from "../../test/render";
import { ModelViewerPage } from "./ModelViewerPage";

const mocks = vi.hoisted(() => ({
  useProject: vi.fn(),
  useCurrentResult: vi.fn(),
  useProjectProcessingStatus: vi.fn(),
  useModelLoader: vi.fn(),
}));

vi.mock("../../features/projects/hooks/useProjects", () => ({
  useProject: mocks.useProject,
}));

vi.mock("../../features/model-viewer/hooks/useCurrentResult", () => ({
  useCurrentResult: mocks.useCurrentResult,
}));

vi.mock("../../features/generation/hooks/useGeneration", () => ({
  useProjectProcessingStatus: mocks.useProjectProcessingStatus,
}));

vi.mock("../../features/model-viewer/hooks/useModelLoader", () => ({
  useModelLoader: mocks.useModelLoader,
}));

vi.mock("../../features/model-viewer/components/ModelViewer", () => ({
  ModelViewer: ({ status }: { status: string }) => (
    <div data-testid="viewer" data-status={status} />
  ),
}));

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Замок Ссо",
  type: "SCENE",
  status: "COMPLETED",
  sourceImageCount: 11,
  resultAvailable: true,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-08T10:00:00Z",
  updatedAt: "2026-11-08T10:05:00Z",
};

const result: GenerationResult = {
  id: "29dd63bc-8ebb-48a3-8808-c1b45f59db6c",
  projectId: project.id,
  taskId: "b738439b-457f-4f42-9257-9a4658ba07dd",
  format: "GLB",
  mimeType: "model/gltf-binary",
  fileSizeBytes: 959_504,
  metadata: {},
  isCurrent: true,
  createdAt: "2026-11-08T10:04:00Z",
};

function renderPage(projectId = project.id) {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId/result" element={<ModelViewerPage />} />
      <Route path="/projects/:projectId" element={<div>Страница проекта</div>} />
      <Route path="/dashboard" element={<div>Панель проектов</div>} />
    </Routes>,
    { route: `/projects/${projectId}/result` },
  );
}

function projectQuery(overrides: Record<string, unknown> = {}) {
  return {
    data: project,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

describe("ModelViewerPage", () => {
  beforeEach(() => {
    mocks.useProject.mockReturnValue(projectQuery());
    mocks.useCurrentResult.mockReturnValue({
      data: result,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    mocks.useProjectProcessingStatus.mockReturnValue({
      data: { projectStatus: "COMPLETED", resultAvailable: true, latestTask: null },
      isError: false,
      error: null,
    });
    mocks.useModelLoader.mockReturnValue({
      status: "loaded",
      model: null,
      stats: { meshes: 1, vertices: 3, triangles: 1, materials: 1, textures: 0 },
      error: null,
      reload: vi.fn(),
    });
  });

  it("opens the viewer for a validated current result", () => {
    renderPage();

    expect(screen.getByTestId("viewer")).toHaveAttribute("data-status", "loaded");
    expect(screen.getByRole("heading", { name: project.name })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать GLB" })).toHaveAttribute(
      "href",
      `/api/v1/projects/${project.id}/download`,
    );
    expect(screen.getByRole("link", { name: "← К проекту" })).toHaveAttribute(
      "href",
      `/projects/${project.id}`,
    );
  });

  it("explains that no result exists yet instead of rendering an empty canvas", () => {
    mocks.useProject.mockReturnValue(
      projectQuery({ data: { ...project, status: "CREATED", resultAvailable: false } }),
    );
    mocks.useCurrentResult.mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderPage();

    expect(screen.getByText("3D-результат ещё не создан")).toBeInTheDocument();
    expect(screen.queryByTestId("viewer")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Перейти к проекту" })).toBeInTheDocument();
  });

  it("shows that generation is running when there is no result yet", () => {
    mocks.useProject.mockReturnValue(
      projectQuery({ data: { ...project, status: "PROCESSING", resultAvailable: false } }),
    );
    mocks.useCurrentResult.mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    mocks.useProjectProcessingStatus.mockReturnValue({
      data: {
        projectStatus: "PROCESSING",
        resultAvailable: false,
        latestTask: { id: "task", status: "PROCESSING" },
      },
      isError: false,
      error: null,
    });

    renderPage();

    expect(screen.getByText("Генерация выполняется")).toBeInTheDocument();
  });

  it("keeps the previous result visible after a failed regeneration", () => {
    mocks.useProjectProcessingStatus.mockReturnValue({
      data: {
        projectStatus: "FAILED",
        resultAvailable: true,
        latestTask: {
          id: "task",
          status: "FAILED",
          taskType: "SCENE",
          stage: "SPARSE_RECONSTRUCTION",
          progressPercent: null,
          statusMessage: null,
          errorCode: "INSUFFICIENT_REGISTERED_IMAGES",
          errorMessage: null,
          createdAt: "2026-11-08T10:00:00Z",
          startedAt: null,
          finishedAt: null,
        },
      },
      isError: false,
      error: null,
    });

    renderPage();

    expect(screen.getByTestId("viewer")).toBeInTheDocument();
    expect(screen.getByText("Показан предыдущий результат")).toBeInTheDocument();
    expect(screen.getByText("Ошибка")).toBeInTheDocument();
  });

  it("reports a missing project", () => {
    mocks.useProject.mockReturnValue(
      projectQuery({
        data: undefined,
        isError: true,
        error: new ApiError({ status: 404, code: "PROJECT_NOT_FOUND", message: "missing" }),
      }),
    );
    mocks.useCurrentResult.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderPage();

    expect(screen.getByText("Проект не найден")).toBeInTheDocument();
  });

  it("rejects a malformed project identifier", () => {
    renderPage("not-a-uuid");

    expect(screen.getByText("Идентификатор проекта в адресе некорректен.")).toBeInTheDocument();
  });

  it("reports a result read failure", () => {
    mocks.useCurrentResult.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError({ status: 500, code: "INTERNAL", message: "boom" }),
      refetch: vi.fn(),
    });

    renderPage();

    expect(screen.getByText("Не удалось загрузить результат")).toBeInTheDocument();
  });
});
