import { fireEvent, render, screen } from "@testing-library/react";
import { BufferAttribute, BufferGeometry, Group, Mesh, MeshStandardMaterial } from "three";
import { describe, expect, it, vi } from "vitest";

import { ModelViewer } from "./ModelViewer";
import { ViewerLoadError } from "../types/viewer.types";

vi.mock("./ModelCanvas", () => ({
  ModelCanvas: () => <div data-testid="model-canvas" />,
}));

function model() {
  const group = new Group();
  const geometry = new BufferGeometry();
  geometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3),
  );
  group.add(new Mesh(geometry, new MeshStandardMaterial()));
  return group;
}

describe("ModelViewer", () => {
  it("renders the canvas and controls for a loaded model", () => {
    render(
      <ModelViewer model={model()} status="loaded" stats={null} error={null} onRetry={vi.fn()} />,
    );

    expect(screen.getByTestId("model-canvas")).toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "Управление просмотром" })).toBeInTheDocument();
    expect(screen.getByText(/ЛКМ — вращение/)).toBeInTheDocument();
    expect(document.querySelector('[data-viewer-state="loaded"]')).not.toBeNull();
  });

  it("shows the loading state while the asset is fetched", () => {
    render(
      <ModelViewer model={null} status="loading" stats={null} error={null} onRetry={vi.fn()} />,
    );

    expect(screen.getByRole("status", { name: "Загрузка 3D-модели" })).toBeInTheDocument();
    expect(screen.getByText("Загрузка 3D-модели…")).toBeInTheDocument();
    expect(screen.queryByTestId("model-canvas")).not.toBeInTheDocument();
  });

  it("shows a readable error and retries", () => {
    const onRetry = vi.fn();
    render(
      <ModelViewer
        model={null}
        status="error"
        stats={null}
        error={new ViewerLoadError("PARSE_FAILED")}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Не удалось показать 3D-модель")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Повторить загрузку" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("toggles grid and background presentation", () => {
    render(
      <ModelViewer model={model()} status="loaded" stats={null} error={null} onRetry={vi.fn()} />,
    );

    const grid = screen.getByRole("button", { name: "Показать или скрыть сетку" });
    expect(grid).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(grid);
    expect(grid).toHaveAttribute("aria-pressed", "false");

    const background = screen.getByRole("button", { name: "Переключить на светлый фон" });
    fireEvent.click(background);
    expect(screen.getByRole("button", { name: "Переключить на тёмный фон" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("does not fail when fullscreen is unavailable", () => {
    render(
      <ModelViewer model={model()} status="loaded" stats={null} error={null} onRetry={vi.fn()} />,
    );

    expect(() =>
      fireEvent.click(screen.getByRole("button", { name: "Открыть на весь экран" })),
    ).not.toThrow();
  });
});
