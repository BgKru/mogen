import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/errors";
import type { Project } from "../../shared/types/api";
import { renderWithProviders } from "../../test/render";
import { CreateProjectPage } from "./CreateProjectPage";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  upload: vi.fn(),
  validate: vi.fn(),
}));

vi.mock("../../features/projects/hooks/useProjects", () => ({
  useCreateProject: () => ({ mutateAsync: mocks.create, isPending: false }),
}));

vi.mock("../../features/image-upload/api/imagesApi", () => ({
  uploadProjectImage: mocks.upload,
}));

vi.mock("../../features/image-upload/utils/validation", () => ({
  validateImageFile: mocks.validate,
}));

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Мой 3D-проект",
  type: "OBJECT",
  status: "CREATED",
  sourceImageCount: 0,
  resultAvailable: false,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-05T12:00:00Z",
  updatedAt: "2026-11-05T12:00:00Z",
};

function renderCreate() {
  return renderWithProviders(
    <Routes>
      <Route path="/projects/new" element={<CreateProjectPage />} />
      <Route path="/projects/:projectId" element={<div>Страница проекта</div>} />
      <Route path="/dashboard" element={<div>Панель</div>} />
    </Routes>,
    { route: "/projects/new" },
  );
}

function fileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error("file input not found");
  }
  return input;
}

function jpeg(name = "photo.jpg"): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: "image/jpeg" });
}

describe("CreateProjectPage", () => {
  beforeEach(() => {
    mocks.validate.mockResolvedValue({ ok: true, dimensions: { width: 640, height: 480 } });
    mocks.create.mockResolvedValue(project);
    mocks.upload.mockResolvedValue({});
  });

  it("switches the upload interface with the generation mode", async () => {
    renderCreate();

    expect(screen.getByText("Загрузить фотографию")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /Реконструкция сцены/ }));

    expect(await screen.findByText("Загрузить изображения")).toBeInTheDocument();
    expect(screen.getByText("Советы для лучшей реконструкции")).toBeInTheDocument();
  });

  it("keeps the submit button disabled until an image is selected", async () => {
    const { container } = renderCreate();

    const submit = screen.getByRole("button", { name: "Создать проект" });
    expect(submit).toBeDisabled();

    fireEvent.change(fileInput(container), { target: { files: [jpeg()] } });

    expect(await screen.findByText("photo.jpg")).toBeInTheDocument();
    await waitFor(() => expect(submit).toBeEnabled());
  });

  it("creates the project, uploads the images and opens the details page", async () => {
    const { container } = renderCreate();
    const file = jpeg();

    fireEvent.change(fileInput(container), { target: { files: [file] } });
    await screen.findByText("photo.jpg");
    fireEvent.click(screen.getByRole("button", { name: "Создать проект" }));

    expect(await screen.findByText("Страница проекта")).toBeInTheDocument();
    expect(mocks.create).toHaveBeenCalledWith({ name: "Мой 3D-проект", type: "OBJECT" });
    expect(mocks.upload).toHaveBeenCalledWith(project.id, file, expect.any(Function));
  });

  it("supports multiple images in scene mode", async () => {
    const { container } = renderCreate();
    fireEvent.click(screen.getByRole("radio", { name: /Реконструкция сцены/ }));

    fireEvent.change(fileInput(container), {
      target: { files: [jpeg("one.jpg"), jpeg("two.jpg")] },
    });

    expect(await screen.findByText("one.jpg")).toBeInTheDocument();
    expect(await screen.findByText("two.jpg")).toBeInTheDocument();
    expect(fileInput(container).multiple).toBe(true);
  });

  it("shows a submission error and stays on the page", async () => {
    mocks.create.mockRejectedValue(
      new ApiError({ status: 500, code: "INTERNAL_SERVER_ERROR", message: "boom" }),
    );
    const { container } = renderCreate();

    fireEvent.change(fileInput(container), { target: { files: [jpeg()] } });
    await screen.findByText("photo.jpg");
    fireEvent.click(screen.getByRole("button", { name: "Создать проект" }));

    expect(
      await screen.findByText("Внутренняя ошибка сервера. Попробуйте позже."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Страница проекта")).not.toBeInTheDocument();
  });
});
