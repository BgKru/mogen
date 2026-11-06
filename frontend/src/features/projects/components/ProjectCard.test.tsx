import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "../../../test/render";
import type { Project } from "../../../shared/types/api";
import { ProjectCard } from "./ProjectCard";

const project: Project = {
  id: "9f1c2c1e-4a6e-4f8f-9d5b-2a7c3e4d5f60",
  name: "Кресло в гостиной",
  type: "OBJECT",
  status: "COMPLETED",
  sourceImageCount: 1,
  resultAvailable: true,
  currentResult: null,
  latestTask: null,
  createdAt: "2026-11-05T12:00:00Z",
  updatedAt: "2026-11-05T12:10:00Z",
};

describe("ProjectCard", () => {
  it("renders project metadata and links to the details page", () => {
    renderWithProviders(<ProjectCard project={project} onDelete={vi.fn()} />);

    expect(screen.getByRole("heading", { name: project.name })).toBeInTheDocument();
    expect(screen.getByText("Генерация объекта")).toBeInTheDocument();
    expect(screen.getByText("Завершено")).toBeInTheDocument();
    expect(screen.getByText("3D-результат доступен")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `Открыть проект ${project.name}` })).toHaveAttribute(
      "href",
      `/projects/${project.id}`,
    );
  });

  it("keeps result availability independent of a failed status", () => {
    renderWithProviders(
      <ProjectCard project={{ ...project, status: "FAILED" }} onDelete={vi.fn()} />,
    );

    expect(screen.getByText("Ошибка")).toBeInTheDocument();
    expect(screen.getByText("3D-результат доступен")).toBeInTheDocument();
  });

  it("asks the caller to delete the project", () => {
    const onDelete = vi.fn();
    renderWithProviders(<ProjectCard project={project} onDelete={onDelete} />);

    fireEvent.click(screen.getByRole("button", { name: `Удалить проект ${project.name}` }));

    expect(onDelete).toHaveBeenCalledWith(project);
  });
});
