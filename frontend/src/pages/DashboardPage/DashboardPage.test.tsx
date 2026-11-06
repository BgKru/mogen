import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project, ProjectPage } from "../../shared/types/api";
import { renderWithProviders } from "../../test/render";
import { DashboardPage } from "./DashboardPage";

const mocks = vi.hoisted(() => ({
  useProjects: vi.fn(),
  useDeleteProject: vi.fn(),
}));

vi.mock("../../features/projects/hooks/useProjects", () => ({
  useProjects: mocks.useProjects,
  useDeleteProject: mocks.useDeleteProject,
}));

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Кресло",
  type: "OBJECT",
  status: "COMPLETED",
  sourceImageCount: 1,
  resultAvailable: true,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-05T12:00:00Z",
  updatedAt: "2026-11-05T12:10:00Z",
};

function page(items: Project[]): ProjectPage {
  return { items, totalCount: items.length, limit: 20, offset: 0 };
}

describe("DashboardPage", () => {
  const deleteMutate = vi.fn();

  beforeEach(() => {
    mocks.useProjects.mockReturnValue({
      data: page([project]),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });
    mocks.useDeleteProject.mockReturnValue({ mutate: deleteMutate, isPending: false });
  });

  it("shows a loading indicator", () => {
    mocks.useProjects.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithProviders(<DashboardPage />);

    expect(screen.getByRole("status", { name: "Загрузка проектов" })).toBeInTheDocument();
  });

  it("shows the empty state when the user has no projects", () => {
    mocks.useProjects.mockReturnValue({
      data: page([]),
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    });

    renderWithProviders(<DashboardPage />);

    expect(screen.getByText("Пока нет проектов")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Создать проект" }).length).toBeGreaterThan(0);
  });

  it("renders the project grid", () => {
    renderWithProviders(<DashboardPage />);

    expect(screen.getByText("Всего проектов: 1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Кресло" })).toBeInTheDocument();
    expect(screen.getByText("Завершено")).toBeInTheDocument();
  });

  it("deletes a project after confirmation", () => {
    renderWithProviders(<DashboardPage />);

    fireEvent.click(screen.getByRole("button", { name: "Удалить проект Кресло" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Удалить" }));

    expect(deleteMutate).toHaveBeenCalledWith(project.id, expect.any(Object));
  });

  it("shows an error and allows retrying", () => {
    const refetch = vi.fn();
    mocks.useProjects.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("network"),
      refetch,
    });

    renderWithProviders(<DashboardPage />);

    expect(screen.getByText("Не удалось загрузить проекты")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
