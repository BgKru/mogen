import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../shared/api/errors";
import type { Project } from "../../../shared/types/api";
import { GenerationPanel } from "./GenerationPanel";

const mocks = vi.hoisted(() => ({
  useProjectProcessingStatus: vi.fn(),
  useStartGeneration: vi.fn(),
}));

vi.mock("../hooks/useGeneration", () => ({
  useProjectProcessingStatus: mocks.useProjectProcessingStatus,
  useStartGeneration: mocks.useStartGeneration,
}));

vi.mock("../api/generationApi", () => ({
  projectDownloadUrl: (projectId: string) => `/api/v1/projects/${projectId}/download`,
}));

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Кружка",
  type: "OBJECT",
  status: "CREATED",
  sourceImageCount: 1,
  resultAvailable: false,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-05T12:00:00Z",
  updatedAt: "2026-11-05T12:00:00Z",
};

const startMutate = vi.fn();

function statusQuery(data: unknown) {
  return { data, isError: false, error: null };
}

function renderPanel(overrides: Partial<Project> = {}, imageCount = 1) {
  return render(
    <MemoryRouter>
      <GenerationPanel project={{ ...project, ...overrides }} imageCount={imageCount} />
    </MemoryRouter>,
  );
}

describe("GenerationPanel", () => {
  beforeEach(() => {
    mocks.useProjectProcessingStatus.mockReturnValue(statusQuery(undefined));
    mocks.useStartGeneration.mockReturnValue({
      mutate: startMutate,
      isPending: false,
      isError: false,
      error: null,
    });
    startMutate.mockReset();
  });

  it("requires exactly one photograph before enabling object generation", () => {
    renderPanel({}, 0);

    expect(screen.getByRole("button", { name: "Создать 3D-модель" })).toBeDisabled();
    expect(screen.getByText(/нужна ровно одна фотография/i)).toBeInTheDocument();
  });

  it("starts generation with the mutation when one photograph is ready", () => {
    renderPanel();

    const button = screen.getByRole("button", { name: "Создать 3D-модель" });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(startMutate).toHaveBeenCalledTimes(1);
  });

  it("shows the real stage and percentage while processing", () => {
    mocks.useProjectProcessingStatus.mockReturnValue(
      statusQuery({
        projectId: project.id,
        projectStatus: "PROCESSING",
        resultAvailable: false,
        latestTask: {
          id: "task-1",
          taskType: "OBJECT",
          status: "PROCESSING",
          stage: "MODEL_GENERATION",
          progressPercent: 40,
          statusMessage: "Running TripoSR inference",
          errorCode: null,
          errorMessage: null,
          createdAt: "2026-11-06T10:00:00Z",
          startedAt: "2026-11-06T10:00:01Z",
          finishedAt: null,
        },
      }),
    );

    renderPanel();

    expect(screen.getByText("Создание 3D-модели")).toBeInTheDocument();
    expect(screen.getByText("Running TripoSR inference")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    expect(screen.getByRole("button", { name: /Идёт генерация/ })).toBeDisabled();
  });

  it("does not fabricate a percentage when the worker has none", () => {
    mocks.useProjectProcessingStatus.mockReturnValue(
      statusQuery({
        projectId: project.id,
        projectStatus: "PROCESSING",
        resultAvailable: false,
        latestTask: {
          id: "task-1",
          taskType: "OBJECT",
          status: "PROCESSING",
          stage: "IMAGE_PREPARATION",
          progressPercent: null,
          statusMessage: null,
          errorCode: null,
          errorMessage: null,
          createdAt: "2026-11-06T10:00:00Z",
          startedAt: "2026-11-06T10:00:01Z",
          finishedAt: null,
        },
      }),
    );

    renderPanel();

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(/Точный процент недоступен/i)).toBeInTheDocument();
    expect(screen.getByText("Подготовка изображения")).toBeInTheDocument();
  });

  it("maps a stable error code to a Russian message and offers retry", () => {
    mocks.useProjectProcessingStatus.mockReturnValue(
      statusQuery({
        projectId: project.id,
        projectStatus: "FAILED",
        resultAvailable: false,
        latestTask: {
          id: "task-1",
          taskType: "OBJECT",
          status: "FAILED",
          stage: "MODEL_GENERATION",
          progressPercent: null,
          statusMessage: "failed",
          errorCode: "GPU_OUT_OF_MEMORY",
          errorMessage: "CUDA out of memory",
          createdAt: "2026-11-06T10:00:00Z",
          startedAt: "2026-11-06T10:00:01Z",
          finishedAt: "2026-11-06T10:05:00Z",
        },
      }),
    );

    renderPanel();

    expect(screen.getByText("Недостаточно видеопамяти для генерации.")).toBeInTheDocument();
    expect(screen.getByText("Код: GPU_OUT_OF_MEMORY")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Повторить генерацию" })).toBeEnabled();
  });

  it("shows the result and a download link when the result is available", () => {
    renderPanel({
      status: "COMPLETED",
      resultAvailable: true,
      currentResult: {
        id: "result-1",
        format: "GLB",
        fileSizeBytes: 2_048_000,
        createdAt: "2026-11-06T10:05:00Z",
      },
    });

    expect(screen.getByText("3D-модель готова")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Скачать GLB" });
    expect(link).toHaveAttribute("href", `/api/v1/projects/${project.id}/download`);
    expect(link).toHaveAttribute("download");
    expect(screen.getByRole("link", { name: "Открыть в 3D" })).toHaveAttribute(
      "href",
      `/projects/${project.id}/result`,
    );
    expect(screen.getByRole("button", { name: "Сгенерировать заново" })).toBeEnabled();
  });

  it("enables scene reconstruction once the minimum image count is reached", () => {
    renderPanel({ type: "SCENE" }, 5);

    expect(screen.getByRole("button", { name: "Реконструировать сцену" })).toBeEnabled();
    expect(screen.getByText(/двигаясь вокруг неё/i)).toBeInTheDocument();
  });

  it("keeps scene reconstruction disabled below the minimum image count", () => {
    renderPanel({ type: "SCENE" }, 2);

    expect(screen.getByRole("button", { name: "Реконструировать сцену" })).toBeDisabled();
    expect(screen.getByText(/нужно не меньше 3 фотографий/i)).toBeInTheDocument();
  });

  it("shows a real scene stage and the scene result label", () => {
    mocks.useProjectProcessingStatus.mockReturnValue(
      statusQuery({
        projectId: project.id,
        projectStatus: "PROCESSING",
        resultAvailable: false,
        latestTask: {
          id: "task-2",
          taskType: "SCENE",
          status: "PROCESSING",
          stage: "DENSE_RECONSTRUCTION",
          progressPercent: null,
          statusMessage: "Reconstructing the dense point cloud",
          errorCode: null,
          errorMessage: null,
          createdAt: "2026-11-07T10:00:00Z",
          startedAt: "2026-11-07T10:00:01Z",
          finishedAt: null,
        },
      }),
    );

    renderPanel({ type: "SCENE" }, 5);

    expect(screen.getByText("Плотная реконструкция")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("surfaces a status request failure", () => {
    mocks.useProjectProcessingStatus.mockReturnValue({
      data: undefined,
      isError: true,
      error: new ApiError({ status: 503, code: "SERVICE_UNAVAILABLE", message: "down" }),
    });

    renderPanel();

    expect(screen.getByText("Не удалось получить статус")).toBeInTheDocument();
  });
});
