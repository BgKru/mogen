import { fireEvent, screen } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/errors";
import type { Project, ProjectImage } from "../../shared/types/api";
import { renderWithProviders } from "../../test/render";
import { ProjectDetailsPage } from "./ProjectDetailsPage";

const mocks = vi.hoisted(() => ({
  useProject: vi.fn(),
  useDeleteProject: vi.fn(),
  useProjectImages: vi.fn(),
  useUploadProjectImage: vi.fn(),
  useDeleteProjectImage: vi.fn(),
}));

vi.mock("../../features/projects/hooks/useProjects", () => ({
  useProject: mocks.useProject,
  useDeleteProject: mocks.useDeleteProject,
}));

vi.mock("../../features/image-upload/hooks/useProjectImages", () => ({
  useProjectImages: mocks.useProjectImages,
  useUploadProjectImage: mocks.useUploadProjectImage,
  useDeleteProjectImage: mocks.useDeleteProjectImage,
}));

vi.mock("../../features/image-upload/api/imagesApi", () => ({
  projectImageContentUrl: (projectId: string, imageId: string) =>
    `/api/v1/projects/${projectId}/images/${imageId}/content`,
}));

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Комната",
  type: "SCENE",
  status: "CREATED",
  sourceImageCount: 2,
  resultAvailable: false,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-05T12:00:00Z",
  updatedAt: "2026-11-05T12:00:00Z",
};

const images: ProjectImage[] = [
  {
    id: "11111111-1111-4111-8111-111111111111",
    projectId: project.id,
    originalFilename: "room-1.jpg",
    mimeType: "image/jpeg",
    fileSizeBytes: 2048,
    width: 1920,
    height: 1080,
    position: 0,
    createdAt: "2026-11-05T12:00:00Z",
  },
  {
    id: "22222222-2222-4222-8222-222222222222",
    projectId: project.id,
    originalFilename: "room-2.jpg",
    mimeType: "image/jpeg",
    fileSizeBytes: 4096,
    width: 1920,
    height: 1080,
    position: 1,
    createdAt: "2026-11-05T12:01:00Z",
  },
];

const deleteProjectMutate = vi.fn();
const deleteImageMutate = vi.fn();
const uploadMutate = vi.fn();

function renderDetails(route = `/projects/${project.id}`) {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/:projectId" element={<ProjectDetailsPage />} />
      <Route path="/dashboard" element={<div>Панель проектов</div>} />
    </Routes>,
    { route },
  );
}

describe("ProjectDetailsPage", () => {
  beforeEach(() => {
    mocks.useProject.mockReturnValue({
      data: project,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    mocks.useProjectImages.mockReturnValue({
      data: { items: images, totalCount: images.length },
      isLoading: false,
      isError: false,
      error: null,
    });
    mocks.useDeleteProject.mockReturnValue({ mutate: deleteProjectMutate, isPending: false });
    mocks.useDeleteProjectImage.mockReturnValue({ mutate: deleteImageMutate, isPending: false });
    mocks.useUploadProjectImage.mockReturnValue({ mutateAsync: uploadMutate, isPending: false });
  });

  it("renders project metadata, images and a disabled generation placeholder", () => {
    renderDetails();

    expect(screen.getByRole("heading", { name: "Комната" })).toBeInTheDocument();
    expect(screen.getAllByText("Реконструкция сцены").length).toBeGreaterThan(0);
    expect(screen.getByText("Создан")).toBeInTheDocument();
    expect(screen.getByAltText("room-1.jpg")).toBeInTheDocument();
    expect(screen.getByAltText("room-2.jpg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Реконструировать сцену" })).toBeDisabled();
    expect(screen.getByText("Ещё не создан")).toBeInTheDocument();
  });

  it("shows the upload area for a project without images", () => {
    mocks.useProject.mockReturnValue({
      data: { ...project, sourceImageCount: 0, type: "OBJECT" },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    mocks.useProjectImages.mockReturnValue({
      data: { items: [], totalCount: 0 },
      isLoading: false,
      isError: false,
      error: null,
    });

    renderDetails();

    expect(screen.getByText("Загрузить фотографию")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать 3D-модель" })).toBeDisabled();
  });

  it("deletes the project after confirmation and returns to the dashboard", () => {
    deleteProjectMutate.mockImplementation((_id: string, options: { onSuccess: () => void }) => {
      options.onSuccess();
    });
    renderDetails();

    fireEvent.click(screen.getByRole("button", { name: "Удалить проект" }));
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));

    expect(deleteProjectMutate).toHaveBeenCalledWith(project.id, expect.any(Object));
    expect(screen.getByText("Панель проектов")).toBeInTheDocument();
  });

  it("deletes one image after confirmation", () => {
    renderDetails();

    fireEvent.click(screen.getByRole("button", { name: "Удалить изображение room-1.jpg" }));
    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));

    expect(deleteImageMutate).toHaveBeenCalledWith(images[0].id, expect.any(Object));
  });

  it("reports an invalid project identifier", () => {
    renderDetails("/projects/not-a-uuid");

    expect(screen.getByText("Проект не найден")).toBeInTheDocument();
  });

  it("reports a missing project", () => {
    mocks.useProject.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError({ status: 404, code: "PROJECT_NOT_FOUND", message: "missing" }),
      refetch: vi.fn(),
    });
    renderDetails();

    expect(screen.getByText("Проект не найден")).toBeInTheDocument();
  });

  it("disables image modification while processing", () => {
    mocks.useProject.mockReturnValue({
      data: { ...project, status: "PROCESSING" },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    renderDetails();

    expect(screen.getByText("Проект обрабатывается")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Удалить изображение room-1.jpg" })).toBeDisabled();
  });
});
